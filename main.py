import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json
import pandas as pd

# --- データベース接続 ---
key_dict = json.loads(st.secrets["textkey"])
creds = service_account.Credentials.from_service_account_info(key_dict)
db = firestore.Client(credentials=creds)

# --- ページ設定 ---
st.set_page_config(page_title="2人だけの家計簿", page_icon="💰", layout="wide")

params = st.query_params
user_code = params.get("user")
if isinstance(user_code, list): user_code = user_code[0]
if user_code is None: user_code = "h"
current_user = "夫" if user_code == "h" else "妻"

page = st.sidebar.radio("メニュー", ["家計簿入力", "リスト管理", "全データ管理"])

# --- [機能1] リスト管理 ---
if page == "リスト管理":
    st.header("🛒 買い物リスト管理")
    with st.form("list_form"):
        place = st.text_input("場所")
        item = st.text_input("品目")
        if st.form_submit_button("登録する"):
            if place and item:
                db.collection("categories").add({"place": place, "item": item})
                st.rerun()
    
    cats_docs = db.collection("categories").stream()
    cats_list = [{"id": doc.id, **doc.to_dict()} for doc in cats_docs]
    for row in cats_list:
        c1, c2 = st.columns([4, 1])
        c1.write(f"📍 {row['place']} / {row['item']}")
        if c2.button("削除", key=f"cat_{row['id']}"):
            db.collection("categories").document(row['id']).delete()
            st.rerun()

# --- [機能2] 全データ管理 ---
elif page == "全データ管理":
    st.header("⚠️ 全データ削除の管理")
    consent_ref = db.collection("consent").document("status")
    consent_doc = consent_ref.get()
    status = consent_doc.to_dict() if consent_doc.exists else {"husband": False, "wife": False}
    
    user_key = "husband" if current_user == "夫" else "wife"
    if st.button(f"全削除に「同意する」を切り替える (現在: {status.get(user_key)})"):
        status[user_key] = not status.get(user_key)
        consent_ref.set(status)
        st.rerun()
    
    if status.get("husband") and status.get("wife"):
        if st.button("本当に全ての履歴を削除する"):
            for doc in db.collection("expenses").stream(): doc.reference.delete()
            consent_ref.set({"husband": False, "wife": False})
            st.rerun()

# --- [機能3] 家計簿入力ページ ---
else:
    st.title("💰 2人だけの家計簿")
    
    cats_docs = db.collection("categories").stream()
    df_cats = pd.DataFrame([doc.to_dict() for doc in cats_docs])
    
    with st.expander("📝 新しい買い物を記録する", expanded=True):
        places = sorted(df_cats["place"].unique().tolist()) if not df_cats.empty else []
        selected_place = st.selectbox("場所", places)
        items_at_place = df_cats[df_cats["place"] == selected_place]["item"].unique().tolist() if selected_place else []
        selected_item = st.selectbox("内容", items_at_place)
        
        with st.form("input_form", clear_on_submit=True):
            amount = st.number_input("金額 (円)", value=None, min_value=0, step=1, format="%d")
            is_reimburse = st.checkbox("全額立て替え (相手に全額請求)")
            if st.form_submit_button("送信する"):
                if amount is not None:
                    db.collection("expenses").add({
                        "person": current_user, "place": selected_place, "item": selected_item,
                        "amount": amount, "is_reimburse": is_reimburse, "timestamp": firestore.SERVER_TIMESTAMP
                    })
                    st.rerun()

    st.write("---")
    docs = db.collection("expenses").stream()
    data = [{"id": doc.id, **doc.to_dict()} for doc in docs]
    
    if data:
        df = pd.DataFrame(data)
        # --- 精算ロジック ---
        # 夫の立て替え(全額) = 夫が入力しis_reimburse=Trueの合計
        # 夫の折半 = 夫が入力しis_reimburse=Falseの合計
        
        def calc_balance(df):
            h_reim = df[(df["person"]=="夫") & (df["is_reimburse"]==True)]["amount"].sum()
            h_split = df[(df["person"]=="夫") & (df["is_reimburse"]==False)]["amount"].sum()
            w_reim = df[(df["person"]=="妻") & (df["is_reimburse"]==True)]["amount"].sum()
            w_split = df[(df["person"]=="妻") & (df["is_reimburse"]==False)]["amount"].sum()
            
            # 妻の夫への支払額 = (夫の立て替え全額 + 夫の折半の半分) - (妻の立て替え全額 + 妻の折半の半分)
            # ※値がマイナスなら夫が妻に払う
            balance = (h_reim + h_split/2) - (w_reim + w_split/2)
            return balance

        bal = calc_balance(df)
        st.subheader("📊 精算結果")
        if bal > 0: st.warning(f"👉 **妻から夫へ {int(bal):,} 円 支払ってください**")
        elif bal < 0: st.warning(f"👉 **夫から妻へ {int(abs(bal)):,} 円 支払ってください**")
        else: st.success("今のところ貸し借りなし！")

        # 履歴表示(省略：前回のコードをそのまま記述)
        # ...
