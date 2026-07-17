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

# --- サイドバーでページ切り替え ---
page = st.sidebar.radio("メニュー", ["家計簿入力", "リスト管理"])

# --- [機能1] リスト管理ページ ---
if page == "リスト管理":
    st.header("🛒 買い物リスト管理")
    with st.form("list_form"):
        place = st.text_input("場所 (例: マイバス)")
        item = st.text_input("品目 (例: ナス)")
        if st.form_submit_button("登録する"):
            if place and item:
                db.collection("categories").add({"place": place, "item": item})
                st.success(f"{place}に{item}を登録しました")
                st.rerun()
            else:
                st.error("場所と品目を入力してください")
    
    st.write("---")
    st.subheader("登録済みのリスト")
    
    cats_docs = db.collection("categories").stream()
    cats_list = [{"id": doc.id, **doc.to_dict()} for doc in cats_docs]
    
    if cats_list:
        df_cats = pd.DataFrame(cats_list).sort_values(by=["place", "item"])
        for i, row in df_cats.iterrows():
            col_a, col_b = st.columns([4, 1])
            col_a.write(f"📍 {row['place']} / 🍎 {row['item']}")
            if col_b.button("削除", key=f"cat_{row['id']}"):
                db.collection("categories").document(row['id']).delete()
                st.rerun()
    else:
        st.info("リストはまだありません。")

# --- [機能2] 家計簿入力ページ ---
else:
    st.title("💰 2人だけの家計簿")
    
    cats_docs = db.collection("categories").stream()
    df_cats = pd.DataFrame([doc.to_dict() for doc in cats_docs])
    
    with st.expander("📝 新しい買い物を記録する", expanded=True):
        places = sorted(df_cats["place"].unique().tolist()) if not df_cats.empty else []
        selected_place = st.selectbox("場所", places)
        
        items_at_place = []
        if selected_place and not df_cats.empty:
            items_at_place = df_cats[df_cats["place"] == selected_place]["item"].unique().tolist()
        
        selected_item = st.selectbox("内容", items_at_place)
        
        with st.form("input_form", clear_on_submit=True):
            amount = st.number_input("金額 (円)", value=None, min_value=0, step=1, format="%d", placeholder="金額を入力")
            submit = st.form_submit_button("送信する")

            if submit:
                if amount is None:
                    st.error("金額を入力してください")
                else:
                    db.collection("expenses").add({
                        "person": current_user,
                        "place": selected_place,
                        "item": selected_item,
                        "amount": amount,
                        "timestamp": firestore.SERVER_TIMESTAMP
                    })
                    st.success(f"{selected_place}で{selected_item}を{amount:,}円で購入しました！")
                    st.rerun()

    # --- 集計と履歴表示 ---
    st.write("---")
    st.subheader("📊 現在の収支状況")
    
    # IDを含めて取得
    docs = db.collection("expenses").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    data = [{"id": doc.id, **doc.to_dict()} for doc in docs]

    if data:
        df = pd.DataFrame(data)
        # 過去データで不足しているカラムを補完
        for col in ["place", "item"]:
            if col not in df.columns: df[col] = "未設定"
        
        df["timestamp"] = pd.to_datetime([d.timestamp() if hasattr(d, 'timestamp') else d for d in df["timestamp"]], unit='s')
        
        # --- 左右に並べる履歴表示（削除ボタン付き） ---
        st.write("### 📜 支払履歴")
        col1, col2 = st.columns(2)
        
        def show_history(target_col, user_name):
            with target_col:
                st.write(f"#### {user_name}の履歴")
                user_df = df[df["person"] == user_name]
                for _, row in user_df.iterrows():
                    c1, c2, c3 = st.columns([2, 2, 1])
                    c1.write(f"{row['timestamp'].strftime('%m/%d %H:%M')}")
                    c2.write(f"{row['place']} / {row['item']} ({row['amount']:,}円)")
                    if c3.button("削除", key=f"exp_{row['id']}"):
                        db.collection("expenses").document(row['id']).delete()
                        st.rerun()

        show_history(col1, "夫")
        show_history(col2, "妻")
        
    else:
        st.info("まだ記録はありません。")
