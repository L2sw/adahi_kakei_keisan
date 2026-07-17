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
            db.collection("categories").add({"place": place, "item": item})
            st.success(f"{place}に{item}を登録しました")
            st.rerun() # 登録後すぐに反映させる
    
    st.write("---")
    st.subheader("登録済みのリスト")
    cats_docs = db.collection("categories").stream()
    cats_data = [doc.to_dict() for doc in cats_docs]
    if cats_data:
        st.dataframe(pd.DataFrame(cats_data), hide_index=True)

# --- [機能2] 家計簿入力ページ ---
else:
    st.title("💰 2人だけの家計簿")
    
    # DBからリストを取得
    cats_docs = db.collection("categories").stream()
    df_cats = pd.DataFrame([doc.to_dict() for doc in cats_docs])
    
    with st.expander("📝 新しい買い物を記録する", expanded=True):
        with st.form("input_form", clear_on_submit=True):
            # 1. 場所の選択
            places = sorted(df_cats["place"].unique().tolist()) if not df_cats.empty else []
            # 場所が変わったことを検知して、下のselectboxを更新させるためにkeyを設定
            selected_place = st.selectbox("場所", places, key="place_select")
            
            # 2. 選択された場所の品目に絞り込み
            items_at_place = []
            if selected_place and not df_cats.empty:
                items_at_place = df_cats[df_cats["place"] == selected_place]["item"].unique().tolist()
            
            selected_item = st.selectbox("内容", items_at_place, key="item_select")
            
            amount = st.number_input("金額 (円)", min_value=0, step=100)
            submit = st.form_submit_button("送信する")

            if submit:
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
    docs = db.collection("expenses").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    data = [doc.to_dict() for doc in docs]

    if data:
        df = pd.DataFrame(data)
        for col in ["place", "item"]:
            if col not in df.columns: df[col] = "未設定"
        
        df["timestamp"] = pd.to_datetime([d.timestamp() if hasattr(d, 'timestamp') else d for d in df["timestamp"]], unit='s')
        df["date_str"] = df["timestamp"].dt.strftime("%m/%d %H:%M")
        
        st.write("### 📜 支払履歴")
        col1, col2 = st.columns(2)
        with col1:
            st.write("#### 夫の履歴")
            h_df = df[df["person"] == "夫"][["date_str", "place", "item", "amount"]]
            h_df.columns = ["日時", "場所", "内容", "金額"]
            st.dataframe(h_df, use_container_width=True, hide_index=True)
        with col2:
            st.write("#### 妻の履歴")
            w_df = df[df["person"] == "妻"][["date_str", "place", "item", "amount"]]
            w_df.columns = ["日時", "場所", "内容", "金額"]
            st.dataframe(w_df, use_container_width=True, hide_index=True)
