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

# URL判定
params = st.query_params
user_code = params.get("user")
if isinstance(user_code, list): user_code = user_code[0]
current_user = "夫" if user_code == "h" else "妻"

# --- メニュー切り替え ---
page = st.sidebar.radio("メニュー", ["入力・収支確認", "場所カテゴリ設定"])

# --- 1. 入力・収支確認ページ ---
if page == "入力・収支確認":
    st.title("💰 2人だけの家計簿")
    
    # 候補リストをDBから取得
    presets = {doc.id: doc.to_dict()["category"] for doc in db.collection("settings").stream()}
    
    with st.expander("📝 新しい買い物を記録する", expanded=True):
        with st.form("input_form", clear_on_submit=True):
            st.write(f"購入者: {current_user}")
            
            # 場所入力
            shop = st.text_input("どこで使った？ (場所)")
            
            # 場所が入力されたら候補を表示
            default_cat = ""
            if shop in presets:
                default_cat = presets[shop]
                st.info(f"💡 推定カテゴリ: {default_cat}")
            
            item = st.text_input("内容 (何に使った？)", value=default_cat)
            amount = st.number_input("金額 (円)", min_value=0, step=100)
            
            submit = st.form_submit_button("送信する")
            if submit:
                db.collection("expenses").add({
                    "person": current_user, "amount": amount, "item": item, "shop": shop,
                    "timestamp": firestore.SERVER_TIMESTAMP
                })
                st.success("追加しました！")

    # 収支・履歴表示（前回同様）
    docs = db.collection("expenses").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    data = [doc.to_dict() for doc in docs]
    if data:
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime([d.timestamp() if hasattr(d, 'timestamp') else d for d in df["timestamp"]], unit='s')
        df["date_str"] = df["timestamp"].dt.strftime("%m/%d %H:%M")
        
        col_a, col_b = st.columns(2)
        col_a.metric("夫の支払い合計", f"{df[df['person']=='夫']['amount'].sum():,}円")
        col_b.metric("妻の支払い合計", f"{df[df['person']=='妻']['amount'].sum():,}円")
        
        st.write("### 📜 支払履歴")
        col1, col2 = st.columns(2)
        for i, (name, col) in enumerate([("夫", col1), ("妻", col2)]):
            with col:
                st.write(f"#### {name}の履歴")
                d = df[df["person"] == name][["date_str", "shop", "item", "amount"]]
                d.columns = ["日時", "場所", "内容", "金額"]
                st.dataframe(d, use_container_width=True, hide_index=True)

# --- 2. 設定ページ ---
else:
    st.title("⚙️ 場所カテゴリ設定")
    with st.form("setting_form"):
        shop_name = st.text_input("場所の名前 (例: セブンイレブン)")
        category = st.text_input("カテゴリ (例: 食費)")
        if st.form_submit_button("保存する"):
            db.collection("settings").document(shop_name).set({"category": category})
            st.success(f"{shop_name} を {category} で登録しました")
            
    st.write("### 現在の登録リスト")
    settings = {doc.id: doc.to_dict()["category"] for doc in db.collection("settings").stream()}
    st.table(pd.DataFrame.from_dict(settings, orient='index', columns=["カテゴリ"]))
