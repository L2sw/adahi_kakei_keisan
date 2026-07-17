import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json

# --- データベース接続 ---
def get_db():
    # GitHub Secretsの "textkey" を使用
    key_dict = json.loads(st.secrets["textkey"])
    creds = service_account.Credentials.from_service_account_info(key_dict)
    return firestore.Client(credentials=creds)

db = get_db()

st.title("💸 2人専用 家計簿アプリ")

# --- 1. 入力フォーム ---
with st.form("input_form"):
    person = st.selectbox("誰が払った？", ["Aさん", "Bさん"])
    amount = st.number_input("金額", min_value=0, step=100)
    item = st.text_input("何に使った？")
    submit = st.form_submit_button("記録する")

    if submit:
        db.collection("expenses").add({
            "person": person,
            "amount": amount,
            "item": item,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        st.success("記録しました！")

# --- 2. データの取得と計算 ---
expenses = [doc.to_dict() for doc in db.collection("expenses").stream()]

if expenses:
    # 集計処理
    total_a = sum(e["amount"] for e in expenses if e["person"] == "Aさん")
    total_b = sum(e["amount"] for e in expenses if e["person"] == "Bさん")
    
    # 計算ロジック
    diff = (total_a - total_b) / 2
    
    # 画面表示
    st.write("---")
    col1, col2 = st.columns(2)
    col1.metric("Aさんの合計", f"{total_a:,}円")
    col2.metric("Bさんの合計", f"{total_b:,}円")
    
    if diff > 0:
        st.info(f"結論: BさんがAさんに {int(diff):,} 円 払うと折半完了です！")
    elif diff < 0:
        st.info(f"結論: AさんがBさんに {int(abs(diff)):,} 円 払うと折半完了です！")
    else:
        st.success("今のところ貸し借りなし！")

    # 履歴表示
    st.write("### 履歴")
    st.table(expenses)
