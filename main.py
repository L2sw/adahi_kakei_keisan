import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json
import pandas as pd

# --- データベース接続 ---
key_dict = json.loads(st.secrets["textkey"])
creds = service_account.Credentials.from_service_account_info(key_dict)
db = firestore.Client(credentials=creds)

# --- パフォーマンス向上 ---
@st.cache_data(ttl=60)
def get_data(collection):
    docs = db.collection(collection).stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

# --- ページ設定 ---
st.set_page_config(page_title="2人だけの家計簿", page_icon="💰", layout="wide")

# --- ユーザー判別 ---
params = st.query_params
user_code = params.get("user")
if isinstance(user_code, list): user_code = user_code[0]
current_user = "大地" if user_code == "h" else "日向子"

page = st.sidebar.radio("メニュー", ["家計簿入力", "リスト管理", "全データ管理"])

# --- [機能1] リスト管理 ---
if page == "リスト管理":
    st.header("🛒 買い物リスト管理")
    # clear_on_submit=True で登録後に欄をクリア
    with st.form("list_form", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 2, 1])
        place = col1.text_input("場所")
        item = col2.text_input("品目")
        if col3.form_submit_button("登録"):
            if place and item:
                db.collection("categories").add({"place": place, "item": item})
                st.cache_data.clear()
                st.rerun()
    
    st.write("---")
    st.subheader("登録済みのリスト")
    cats = get_data("categories")
    if cats:
        df_cats = pd.DataFrame(cats).sort_values(by=["place", "item"])
        # 各行に削除ボタンを配置して誤操作を防止
        for _, row in df_cats.iterrows():
            c1, c2, c3 = st.columns([2, 2, 1])
            c1.write(row['place'])
            c2.write(row['item'])
            if c3.button("削除", key=f"del_{row['id']}"):
                db.collection("categories").document(row['id']).delete()
                st.cache_data.clear()
                st.rerun()
    else:
        st.info("リストはまだありません。")

# --- [機能2] 全データ管理 ---
elif page == "全データ管理":
    st.header("⚠️ 全データ削除の管理")
    consent_ref = db.collection("consent").document("status")
    status = consent_ref.get().to_dict() or {"daichi": False, "hinako": False}
    
    st.write(f"大地の同意: {'✅' if status.get('daichi', False) else '❌'}")
    st.write(f"日向子の同意: {'✅' if status.get('hinako', False) else '❌'}")
    
    user_key = "daichi" if current_user == "大地" else "hinako"
    if st.button(f"同意を切り替える (現在: {status.get(user_key, False)})"):
        status[user_key] = not status.get(user_key, False)
        consent_ref.set(status)
        st.rerun()
    
    if status.get("daichi", False) and status.get("hinako", False):
        if st.button("本当に全ての履歴を削除する"):
            for doc in db.collection("expenses").stream(): doc.reference.delete()
            consent_ref.set({"daichi": False, "hinako": False})
            st.cache_data.clear()
            st.rerun()

# --- [機能3] 家計簿入力ページ ---
else:
    st.markdown("<h2 style='text-align: left; color: #333;'>💰 2人だけの家計簿</h2>", unsafe_allow_html=True)
    
    with st.expander("📝 新しい買い物を記録する", expanded=True):
        # テキスト入力で自由入力可能に
        selected_place = st.text_input("場所")
        selected_item = st.text_input("内容")
        
        with st.form("input_form", clear_on_submit=True):
            amount = st.number_input("金額 (円)", value=None, min_value=0, step=1, format="%d")
            is_reimburse = st.checkbox("全立替")
            if st.form_submit_button("送信する"):
                if amount is not None and selected_place and selected_item:
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
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)
        df["is_reimburse"] = df["is_reimburse"].fillna(False).astype(bool)
        df["timestamp"] = pd.to_datetime([d.get("timestamp") if isinstance(d, dict) else d for d in df["timestamp"]], unit='s')
        
        # --- 精算ロジック ---
        def get_totals(user):
            user_df = df[df["person"] == user]
            reim = user_df[user_df["is_reimburse"]]["amount"].sum()
            split = user_df[~user_df["is_reimburse"]]["amount"].sum()
            return reim, split

        d_r, d_s = get_totals("大地")
        h_r, h_s = get_totals("日向子")
        balance = (d_r + d_s/2) - (h_r + h_s/2)
        
        st.subheader("📊 精算結果")
        if balance > 0: st.warning(f"👉 **日向子から大地へ {int(balance):,} 円 支払ってください**")
        elif balance < 0: st.warning(f"👉 **大地から日向子へ {int(abs(balance)):,} 円 支払ってください**")
        else: st.success("貸し借りなし！")
        
        # --- 履歴表示 ---
        col1, col2 = st.columns(2)
        def show_history(col, user):
            with col:
                st.subheader(f"{user}の履歴")
                user_df = df[df["person"] == user].copy()
                user_df["日時"] = user_df["timestamp"].dt.strftime("%m/%d %H:%M")
                st.dataframe(user_df[["日時", "place", "item", "amount", "is_reimburse"]].rename(
                    columns={"place":"場所", "item":"内容", "amount":"円", "is_reimburse":"全立替"}), 
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
