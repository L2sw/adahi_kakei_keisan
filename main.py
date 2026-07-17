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
    
    st.write("---")
    st.subheader("登録済みのリスト")
    cats = [doc.to_dict() for doc in db.collection("categories").stream()]
    if cats:
        st.dataframe(pd.DataFrame(cats), hide_index=True)

# --- [機能2] 家計簿入力ページ ---
else:
    st.title("💰 2人だけの家計簿")
    st.write(f"現在ログイン中: **{current_user}** さん")

    # DBから場所と品目のリストを取得
    cats = [doc.to_dict() for doc in db.collection("categories").stream()]
    df_cats = pd.DataFrame(cats) if cats else pd.DataFrame(columns=["place", "item"])

    with st.expander("📝 新しい買い物を記録する", expanded=True):
        with st.form("input_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            # 場所の選択肢（重複を除去）
            places = df_cats["place"].unique().tolist() if not df_cats.empty else []
            selected_place = col1.selectbox("場所", places)
            
            # 選択された場所に基づく品目の絞り込み
            items_at_place = df_cats[df_cats["place"] == selected_place]["item"].tolist() if selected_place else []
            selected_item = col2.selectbox("内容", items_at_place)
            
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

    # --- 集計と履歴表示 ---
    st.write("---")
    st.subheader("📊 現在の収支状況")
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
        if diff > 0: st.warning(f"👉 妻が夫へ {int(diff):,} 円 渡すと折半完了です")
        elif diff < 0: st.warning(f"👉 夫が妻へ {int(abs(diff)):,} 円 渡すと折半完了です")
        else: st.success("今のところ貸し借りなし！")

        st.write("---")
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
