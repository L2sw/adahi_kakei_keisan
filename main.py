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

# --- ユーザー判別 ---
params = st.query_params
user_code = params.get("user")
if isinstance(user_code, list): user_code = user_code[0]
if user_code is None: user_code = "h"
current_user = "夫" if user_code == "h" else "妻"

# --- サイドバー ---
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

# --- [機能2] 全データ管理 (全削除機能) ---
elif page == "全データ管理":
    st.header("⚠️ 全データ削除の管理")
    
    # 同意状態の取得
    consent_ref = db.collection("consent").document("status")
    consent_doc = consent_ref.get()
    status = consent_doc.to_dict() if consent_doc.exists else {"husband": False, "wife": False}
    
    st.write(f"夫の同意: {'✅' if status.get('husband') else '❌'}")
    st.write(f"妻の同意: {'✅' if status.get('wife') else '❌'}")
    
    # 同意切り替えボタン
    user_key = "husband" if current_user == "夫" else "wife"
    new_state = not status.get(user_key)
    if st.button(f"全削除に「同意する」を切り替える (現在: {new_state})"):
        status[user_key] = new_state
        consent_ref.set(status)
        st.rerun()
    
    # 全削除の実行判定
    if status.get("husband") and status.get("wife"):
        st.error("二人の同意が揃いました！")
        if st.button("本当に全ての履歴を削除する"):
            # データの全削除
            docs = db.collection("expenses").stream()
            for doc in docs:
                doc.reference.delete()
            # 同意をリセット
            consent_ref.set({"husband": False, "wife": False})
            st.success("全ての履歴を削除しました！")
            st.rerun()
    else:
        st.info("二人ともが同意すると、削除ボタンが表示されます。")

# --- [機能3] 家計簿入力 ---
else:
    st.title("💰 2人だけの家計簿")
    # (入力および履歴表示部分は省略せずそのまま記述してください)
    # ... (前回の履歴表示ロジックをここに配置) ...
