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
                st.rerun()
    
    cats_docs = db.collection("categories").stream()
    cats_list = [{"id": doc.id, **doc.to_dict()} for doc in cats_docs]
    if cats_list:
        df_cats = pd.DataFrame(cats_list).sort_values(by=["place", "item"])
        for _, row in df_cats.iterrows():
            c1, c2 = st.columns([4, 1])
            c1.write(f"📍 {row['place']} / 🍎 {row['item']}")
            if c2.button("削除", key=f"cat_{row['id']}"):
                db.collection("categories").document(row['id']).delete()
                st.rerun()

# --- [機能2] 家計簿入力ページ ---
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
            amount = st.number_input("金額 (円)", value=None, min_value=0, step=1, format="%d", placeholder="金額を入力")
            if st.form_submit_button("送信する"):
                if amount is not None:
                    db.collection("expenses").add({
                        "person": current_user,
                        "place": selected_place,
                        "item": selected_item,
                        "amount": amount,
                        "timestamp": firestore.SERVER_TIMESTAMP
                    })
                    st.rerun()

    st.write("---")
    st.subheader("📜 支払履歴 (自分の履歴のみ削除可能)")
    
    docs = db.collection("expenses").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    data = [{"id": doc.id, **doc.to_dict()} for doc in docs]
    df = pd.DataFrame(data)
    if not df.empty:
        df["timestamp"] = pd.to_datetime([d.timestamp() if hasattr(d, 'timestamp') else d for d in df["timestamp"]], unit='s')
        df["日時"] = df["timestamp"].dt.strftime("%m/%d %H:%M")
        
        col1, col2 = st.columns(2)
        
        def show_history_table(target_col, user_name):
            with target_col:
                st.write(f"#### {user_name}の履歴")
                user_df = df[df["person"] == user_name].copy()
                
                # 表形式を表示
                st.dataframe(user_df[["日時", "place", "item", "amount"]].rename(columns={"place":"場所", "item":"内容", "amount":"金額"}), 
                             use_container_width=True, hide_index=True)
                
                # そのユーザーの履歴だけを消せるUI
                if user_name == current_user:
                    with st.expander(f"⚠️ {user_name}の履歴を削除する"):
                        # 削除したい項目をプルダウンで選ぶ
                        del_target = st.selectbox("削除する項目を選択", user_df.apply(lambda r: f"{r['日時']} {r['place']} {r['item']} {r['amount']}円", axis=1))
                        if st.button("この項目を削除", key=f"del_{user_name}"):
                            # 一致するIDを探して削除
                            target_id = user_df[user_df.apply(lambda r: f"{r['日時']} {r['place']} {r['item']} {r['amount']}円", axis=1) == del_target]["id"].values[0]
                            db.collection("expenses").document(target_id).delete()
                            st.rerun()

        show_history_table(col1, "夫")
        show_history_table(col2, "妻")
