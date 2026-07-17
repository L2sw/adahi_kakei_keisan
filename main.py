import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json
import pandas as pd

# --- データベース接続 ---
key_dict = json.loads(st.secrets["textkey"])
creds = service_account.Credentials.from_service_account_info(key_dict)
db = firestore.Client(credentials=creds)

# --- パフォーマンス向上: キャッシュを使ってデータ読み込みを効率化 ---
@st.cache_data(ttl=60)
def get_data(collection):
    docs = db.collection(collection).stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

# --- ページ設定 ---
st.set_page_config(page_title="2人だけの家計簿 HD", page_icon="💰", layout="wide")

# --- ユーザー判別 ---
params = st.query_params
user_code = params.get("user")
if isinstance(user_code, list): user_code = user_code[0]
current_user = "大地" if user_code == "h" else "日向子"

page = st.sidebar.radio("メニュー", ["台帳入力", "リスト管理", "全データ削除"])

# --- [機能1] リスト管理 ---
if page == "品ものリスト管理":
    st.header("🛒 買い物リスト管理")
    with st.form("list_form"):
        place = st.text_input("場所")
        item = st.text_input("品目")
        if st.form_submit_button("登録する"):
            if place and item:
                db.collection("categories").add({"place": place, "item": item})
                st.cache_data.clear() # 更新時にキャッシュをクリア
                st.rerun()
    
    cats = get_data("categories")
    if cats:
        df_cats = pd.DataFrame(cats).sort_values(by=["place", "item"])
        for _, row in df_cats.iterrows():
            c1, c2 = st.columns([4, 1])
            c1.write(f"📍 {row['place']} / {row['item']}")
            if c2.button("削除", key=f"cat_{row['id']}"):
                db.collection("categories").document(row['id']).delete()
                st.cache_data.clear()
                st.rerun()

# --- [機能2] 全データ管理 ---
elif page == "全データ管理":
    st.header("⚠️ 全データ削除の管理")
    consent_ref = db.collection("consent").document("status")
    status = consent_ref.get().to_dict() or {"husband": False, "wife": False}
    
    st.write(f"大地の同意: {'✅' if status['husband'] else '❌'}")
    st.write(f"日向子の同意: {'✅' if status['wife'] else '❌'}")
    
    user_key = "husband" if current_user == "大地" else "wife"
    if st.button(f"同意を切り替える (現在: {status[user_key]})"):
        status[user_key] = not status[user_key]
        consent_ref.set(status)
        st.rerun()
    
    if status["husband"] and status["wife"]:
        if st.button("本当に全ての履歴を削除する"):
            for doc in db.collection("expenses").stream(): doc.reference.delete()
            consent_ref.set({"husband": False, "wife": False})
            st.cache_data.clear()
            st.rerun()

# --- [機能3] 家計簿入力ページ ---
else:
    st.title("💰 2人だけの家計簿")
    
    cats = get_data("categories")
    df_cats = pd.DataFrame(cats) if cats else pd.DataFrame(columns=["place", "item"])
    
    with st.expander("📝 新しい買い物を記録する", expanded=True):
        places = sorted(df_cats["place"].unique().tolist()) if not df_cats.empty else []
        selected_place = st.selectbox("場所", places)
        items = df_cats[df_cats["place"] == selected_place]["item"].unique().tolist() if selected_place else []
        selected_item = st.selectbox("内容", items)
        
        with st.form("input_form", clear_on_submit=True):
            amount = st.number_input("金額 (円)", value=None, min_value=0, step=1, format="%d")
            is_reimburse = st.checkbox("全建替")
            if st.form_submit_button("送信する"):
                if amount is not None:
                    db.collection("expenses").add({
                        "person": current_user, "place": selected_place, "item": selected_item,
                        "amount": int(amount), "is_reimburse": bool(is_reimburse), "timestamp": firestore.SERVER_TIMESTAMP
                    })
                    st.cache_data.clear()
                    st.rerun()

    st.write("---")
    expenses = get_data("expenses")
    if expenses:
        df = pd.DataFrame(expenses)
        # データの型を揃える
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)
        df["is_reimburse"] = df["is_reimburse"].fillna(False).astype(bool)
        df["timestamp"] = pd.to_datetime([d.get("timestamp") if isinstance(d, dict) else d for d in df["timestamp"]], unit='s')
        
        # --- 精算ロジック ---
        def get_totals(user):
            user_df = df[df["person"] == user]
            reim = user_df[user_df["is_reimburse"]]["amount"].sum()
            split = user_df[~user_df["is_reimburse"]]["amount"].sum()
            return reim, split

        h_r, h_s = get_totals("大地")
        w_r, w_s = get_totals("日向子")
        
        balance = (h_r + h_s/2) - (w_r + w_s/2)
        
        st.subheader("📊 精算結果")
        if balance > 0: st.warning(f"👉 日向子から大地へ **{int(balance):,} 円** 支払ってください")
        elif balance < 0: st.warning(f"👉 大地から日向子へ **{int(abs(balance)):,} 円** 支払ってください")
        else: st.success("貸し借りなし！")
        
        # --- 履歴表示 ---
        col1, col2 = st.columns(2)
        def show_history(col, user):
            with col:
                st.subheader(f"{user}の履歴")
                user_df = df[df["person"] == user].copy()
                user_df["日時"] = user_df["timestamp"].dt.strftime("%m/%d %H:%M")
                st.dataframe(user_df[["日時", "place", "item", "amount", "is_reimburse"]].rename(
                    columns={"place":"場所", "item":"内容", "amount":"円", "is_reimburse":"全建替"}), 
                    use_container_width=True, hide_index=True)
                
                if user == current_user:
                    with st.expander("⚙️ 履歴削除"):
                        options = {f"{r['日時']} {r['place']} {r['item']} {r['amount']}円": r['id'] for _, r in user_df.iterrows()}
                        sel = st.selectbox("選択", options.keys())
                        if st.button("削除", key=f"del_{user}"):
                            db.collection("expenses").document(options[sel]).delete()
                            st.cache_data.clear()
                            st.rerun()

        show_history(col1, "大地")
        show_history(col2, "日向子")
