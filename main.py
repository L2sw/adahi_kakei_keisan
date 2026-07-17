import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json
import pandas as pd

# --- データベース接続 ---
key_dict = json.loads(st.secrets["textkey"])
creds = service_account.Credentials.from_service_account_info(key_dict)
db = firestore.Client(credentials=creds)

# --- ページ設定とユーザー判別 ---
st.set_page_config(page_title="2人だけの家計簿", page_icon="💰", layout="wide")

params = st.query_params
user_code = params.get("user")
if isinstance(user_code, list):
    user_code = user_code[0]
if user_code is None:
    user_code = "h"

current_user = "夫" if user_code == "h" else "妻"

st.title("💰 2人だけの家計簿")
st.write(f"現在ログイン中: **{current_user}** さん")

# --- 1. 入力フォーム ---
with st.expander("📝 新しい買い物を記録する", expanded=True):
    # 過去の場所リストを取得（候補用）
    docs = db.collection("expenses").stream()
    all_data = [d.to_dict() for d in docs]
    places = list(set([d.get("place", "") for d in all_data if d.get("place")]))
    
    with st.form("input_form", clear_on_submit=True):
        st.write(f"購入者: {current_user}")
        
        # 場所の入力（新規入力または選択）
        selected_place = st.selectbox("場所 (どこで？)", [""] + places, index=0)
        input_place = st.text_input("場所（リストにない場合）")
        final_place = input_place if input_place else selected_place
        
        # 内容の候補を過去データから検索
        candidates = []
        if final_place:
            candidates = list(set([d.get("item", "") for d in all_data if d.get("place") == final_place]))
        
        selected_item = st.selectbox("内容 (何に使った？)", [""] + candidates)
        input_item = st.text_input("内容（リストにない場合）")
        final_item = input_item if input_item else selected_item
        
        amount = st.number_input("金額 (円)", min_value=0, step=100)
        submit = st.form_submit_button("送信する")

        if submit:
            if not final_place or not final_item:
                st.error("場所と内容を入力してください！")
            else:
                db.collection("expenses").add({
                    "person": current_user,
                    "amount": amount,
                    "item": final_item,
                    "place": final_place,
                    "timestamp": firestore.SERVER_TIMESTAMP
                })
                st.success(f"{current_user}さんが {final_place} で {final_item} に {amount:,}円 使いました！")

# --- 2. データの取得と表示 ---
st.write("---")
st.subheader("📊 現在の収支状況")

# 最新データ再取得
docs = db.collection("expenses").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
data = [doc.to_dict() for doc in docs]

if data:
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime([d.timestamp() if hasattr(d, 'timestamp') else d for d in df["timestamp"]], unit='s')
    df["date_str"] = df["timestamp"].dt.strftime("%m/%d %H:%M")
    
    total_husband = df[df["person"] == "夫"]["amount"].sum()
    total_wife = df[df["person"] == "妻"]["amount"].sum()
    
    col_a, col_b = st.columns(2)
    col_a.metric("夫の支払い合計", f"{total_husband:,}円")
    col_b.metric("妻の支払い合計", f"{total_wife:,}円")
    
    diff = (total_husband - total_wife) / 2
    if diff > 0:
        st.warning(f"👉 妻が夫へ {int(diff):,} 円 渡すと折半完了です")
    elif diff < 0:
        st.warning(f"👉 夫が妻へ {int(abs(diff)):,} 円 渡すと折半完了です")
    else:
        st.success("今のところ貸し借りなし！")

    # 左右に並べる履歴表示
    st.write("---")
    st.write("### 📜 支払履歴")
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("#### 夫の履歴")
        husband_df = df[df["person"] == "夫"][["date_str", "place", "item", "amount"]]
        husband_df.columns = ["日時", "場所", "内容", "金額"]
        st.dataframe(husband_df, use_container_width=True, hide_index=True)
        
    with col2:
        st.write("#### 妻の履歴")
        wife_df = df[df["person"] == "妻"][["date_str", "place", "item", "amount"]]
        wife_df.columns = ["日時", "場所", "内容", "金額"]
        st.dataframe(wife_df, use_container_width=True, hide_index=True)
else:
    st.info("まだ記録はありません。買い物を追加してみましょう！")
