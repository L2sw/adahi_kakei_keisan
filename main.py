import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json
import pandas as pd

# --- データベース接続 ---
# GitHub Secretsから "textkey" を読み込む
key_dict = json.loads(st.secrets["textkey"])
creds = service_account.Credentials.from_service_account_info(key_dict)
db = firestore.Client(credentials=creds)

# --- ページ設定とユーザー判別 ---
st.set_page_config(page_title="2人だけの家計簿", page_icon="💰")

# URLパラメータ ?user=h または ?user=w を取得
params = st.query_params
# 値を確実に文字列として取得するための処理
user_code = params.get("user")
if isinstance(user_code, list):
    user_code = user_code[0]
if user_code is None:
    user_code = "h"  # 指定がなければデフォルトは「夫(h)」

# コードから名前に変換
current_user = "夫" if user_code == "h" else "妻"

st.title("💰 2人だけの家計簿")
st.write(f"現在ログイン中: **{current_user}** さん")

# --- 1. 入力フォーム ---
with st.expander("📝 新しい買い物を記録する", expanded=True):
    with st.form("input_form", clear_on_submit=True):
        st.write(f"購入者: {current_user}")
        
        amount = st.number_input("金額 (円)", min_value=0, step=100)
        item = st.text_input("内容 (何に使った？)")
        submit = st.form_submit_button("送信する")

        if submit:
            if item == "":
                st.error("内容を入力してください！")
            else:
                db.collection("expenses").add({
                    "person": current_user,
                    "amount": amount,
                    "item": item,
                    "timestamp": firestore.SERVER_TIMESTAMP
                })
                st.success(f"{current_user}さんが {amount:,}円 を追加しました！")

# --- 2. データの表示と計算 ---
st.write("---")
st.subheader("📊 現在の収支状況")

# データを取得してデータフレームに変換
docs = db.collection("expenses").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
data = [doc.to_dict() for doc in docs]

if data:
    df = pd.DataFrame(data)
    
    # 夫と妻の合計を計算
    total_husband = df[df["person"] == "夫"]["amount"].sum()
    total_wife = df[df["person"] == "妻"]["amount"].sum()
    
    # 計算ロジック
    diff = (total_husband - total_wife) / 2
    
    # 画面表示
    col_a, col_b = st.columns(2)
    col_a.metric("夫の支払い合計", f"{total_husband:,}円")
    col_b.metric("妻の支払い合計", f"{total_wife:,}円")
    
    if diff > 0:
        st.warning(f"👉 妻が夫へ {int(diff):,} 円 渡すと折半完了です")
    elif diff < 0:
        st.warning(f"👉 夫が妻へ {int(abs(diff)):,} 円 渡すと折半完了です")
    else:
        st.success("今のところ貸し借りなし！")

    # 履歴一覧表示
    st.write("### 履歴一覧")
    
    # タイムスタンプを読みやすい形式に変換
    if "timestamp" in df.columns:
        # Firestoreのタイムスタンプをdatetimeに変換
        df["timestamp"] = pd.to_datetime([d.timestamp() if hasattr(d, 'timestamp') else d for d in df["timestamp"]], unit='s')
        display_df = df[["timestamp", "person", "item", "amount"]]
        st.dataframe(display_df, use_container_width=True)
    else:
        st.dataframe(df, use_container_width=True)
else:
    st.info("まだ記録はありません。買い物を追加してみましょう！")
