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
st.set_page_config(page_title="2人だけの家計簿", page_icon="🦈", layout="wide")

# --- ユーザー判別 ---
params = st.query_params
user_code = params.get("user")
if isinstance(user_code, list): user_code = user_code[0]
current_user = "大地" if user_code == "h" else "日向子"

page = st.sidebar.radio("メニュー", ["台帳入力", "リスト管理", "全データ削除"])

# --- [機能1] リスト管理 ---
if page == "リスト管理":
    st.header("🐖 リスト管理")
    
    if "last_place" not in st.session_state:
        st.session_state.last_place = ""

    with st.form("list_form"):
        place = st.text_input("場所", value=st.session_state.last_place)
        item = st.text_input("品目")
        if st.form_submit_button("登録する"):
            if place and item:
                # 重複チェック
                cats = get_data("categories")
                if any(c["place"] == place and c["item"] == item for c in cats):
                    st.error("その場所と品目の組み合わせは既に登録されています！")
                else:
                    db.collection("categories").add({"place": place, "item": item})
                    st.session_state.last_place = place
                    st.cache_data.clear()
                    st.rerun()

    st.write("---")
    st.subheader("登録済みのリスト")
    cats = get_data("categories")
    if cats:
        df_cats = pd.DataFrame(cats).sort_values(by=["place", "item"])
        display_df = df_cats[["place", "item"]].rename(columns={"place": "場所", "item": "品目"})
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        
        with st.expander("🗑️ リストから削除する"):
            options = {f"{r['place']} - {r['item']}": r['id'] for _, r in df_cats.iterrows()}
            selected_cat = st.selectbox("削除する項目を選択", list(options.keys()))
            if st.button("この項目を削除"):
                db.collection("categories").document(options[selected_cat]).delete()
                st.cache_data.clear()
                st.rerun()

# --- [機能2] 全データ管理 ---
elif page == "全データ削除":
    st.header("⚠️ 全データ削除")
    consent_ref = db.collection("consent").document("status")
    status = consent_ref.get().to_dict() or {"daichi": False, "hinako": False}
    
    # 同意ステータス表示
    st.write(f"大地: {'✅ 同意済み' if status.get('daichi') else '❌ 未同意'}")
    st.write(f"日向子: {'✅ 同意済み' if status.get('hinako') else '❌ 未同意'}")
    
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
    st.markdown("<h2 style='text-align: left; color: #333;'>🐘 2人だけの家計簿</h2>", unsafe_allow_html=True)
    cats = get_data("categories")
    df_cats = pd.DataFrame(cats) if cats else pd.DataFrame(columns=["place", "item"])
    
    with st.expander("🐔記録する", expanded=True):
        col1, col2 = st.columns(2)
        places = sorted(df_cats["place"].unique().tolist())
        sel_p = col1.selectbox("場所選択", [""] + places)
        text_p = col1.text_input("場所直接入力(優先)")
        selected_place = text_p if text_p else sel_p
        
        items = df_cats[df_cats["place"] == selected_place]["item"].unique().tolist() if selected_place in places else []
        sel_i = col2.selectbox("品目選択", [""] + items)
        text_i = col2.text_input("品目直接入力(優先)")
        selected_item = text_i if text_i else sel_i
        
        with st.form("input_form", clear_on_submit=True):
            amount = st.number_input("金額 (円)", value=None, min_value=0, step=1, format="%d")
            is_reimburse = st.checkbox("全立替")
            if st.form_submit_button("送信"):
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
        
        # 精算ロジック
        d_r = df[(df["person"] == "大地") & (df["is_reimburse"])]["amount"].sum()
        d_s = df[(df["person"] == "大地") & (~df["is_reimburse"])]["amount"].sum()
        h_r = df[(df["person"] == "日向子") & (df["is_reimburse"])]["amount"].sum()
        h_s = df[(df["person"] == "日向子") & (~df["is_reimburse"])]["amount"].sum()
        
        balance = (d_r + d_s/2) - (h_r + h_s/2)
        
        st.subheader("🐢 精算結果")
        if balance > 0: st.warning(f"💗 **日向子から大地へ {int(balance):,} 円 支払ってください**")
        elif balance < 0: st.warning(f"🐢 **大地から日向子へ {int(abs(balance)):,} 円 支払ってください**")
        else: st.success("貸し借りなし！")
        
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
                    with st.expander("🍅 履歴削除"):
                        options = {f"{r['日時']} {r['place']} {r['item']} {r['amount']}円": r['id'] for _, r in user_df.iterrows()}
                        sel = st.selectbox("選択", options.keys())
                        if st.button("削除", key=f"del_{user}"):
                            db.collection("expenses").document(options[sel]).delete()
                            st.cache_data.clear()
                            st.rerun()

        show_history(col1, "大地")
        show_history(col2, "日向子")
