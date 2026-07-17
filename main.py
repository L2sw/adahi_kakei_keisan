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
    
    st.write("---")
    st.subheader("登録済みのリスト")
    cats_docs = db.collection("categories").stream()
    cats_list = [{"id": doc.id, **doc.to_dict()} for doc in cats_docs]
    if cats_list:
        df_cats = pd.DataFrame(cats_list).sort_values(by=["place", "item"])
        for _, row in df_cats.iterrows():
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
    
    st.write(f"夫の同意: {'✅' if status.get('husband') else '❌'}")
    st.write(f"妻の同意: {'✅' if status.get('wife') else '❌'}")
    
    user_key = "husband" if current_user == "夫" else "wife"
    if st.button(f"全削除に「同意する」を切り替える (現在: {status.get(user_key)})"):
        status[user_key] = not status.get(user_key)
        consent_ref.set(status)
        st.rerun()
    
    if status.get("husband") and status.get("wife"):
        st.error("二人の同意が揃いました！")
        if st.button("本当に全ての履歴を削除する"):
            for doc in db.collection("expenses").stream(): doc.reference.delete()
            consent_ref.set({"husband": False, "wife": False})
            st.rerun()
    else:
        st.info("二人ともが同意すると、削除ボタンが表示されます。")

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
            amount = st.number_input("金額 (円)", value=None, min_value=0, step=1, format="%d", placeholder="金額を入力")
            is_reimburse = st.checkbox("全額立て替え (相手に全額請求)")
            if st.form_submit_button("送信する"):
                if amount is not None:
                    db.collection("expenses").add({
                        "person": current_user, "place": selected_place, "item": selected_item,
                        "amount": amount, "is_reimburse": is_reimburse, "timestamp": firestore.SERVER_TIMESTAMP
                    })
                    st.rerun()

    st.write("---")
    docs = db.collection("expenses").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    data = [{"id": doc.id, **doc.to_dict()} for doc in docs]
    
    if data:
        df = pd.DataFrame(data)
        # カラムの補完処理（KeyError対策）
        for col in ["place", "item", "amount", "is_reimburse"]:
            if col not in df.columns:
                df[col] = False if col == "is_reimburse" else "-"
        
        df["timestamp"] = pd.to_datetime([d.timestamp() if hasattr(d, 'timestamp') else d for d in df["timestamp"]], unit='s')
        df["日時"] = df["timestamp"].dt.strftime("%m/%d %H:%M")
        
        # --- 精算結果計算 ---
        h_reim = df[(df["person"]=="夫") & (df["is_reimburse"]==True)]["amount"].sum()
        h_split = df[(df["person"]=="夫") & (df["is_reimburse"]==False)]["amount"].sum()
        w_reim = df[(df["person"]=="妻") & (df["is_reimburse"]==True)]["amount"].sum()
        w_split = df[(df["person"]=="妻") & (df["is_reimburse"]==False)]["amount"].sum()
        
        # 精算式: 夫の請求分(立て替え全額+折半半分) - 妻の請求分(立て替え全額+折半半分)
        balance = (h_reim + h_split/2) - (w_reim + w_split/2)
        
        st.subheader("📊 精算結果")
        if balance > 0: st.warning(f"👉 **妻から夫へ {int(balance):,} 円 支払ってください**")
        elif balance < 0: st.warning(f"👉 **夫から妻へ {int(abs(balance)):,} 円 支払ってください**")
        else: st.success("今のところ貸し借りなし！")
        
        # --- 履歴表示 ---
        col1, col2 = st.columns(2)
        def show_history_compact(target_col, user_name):
            with target_col:
                st.subheader(f"{user_name}の履歴")
                user_df = df[df["person"] == user_name].copy()
                display_df = user_df[["日時", "place", "item", "amount", "is_reimburse"]].rename(
                    columns={"place":"場所", "item":"内容", "amount":"円", "is_reimburse":"全額請求"}
                )
                st.dataframe(display_df, use_container_width=True, hide_index=True)
                
                if user_name == current_user:
                    with st.expander(f"⚙️ {user_name}の履歴を削除"):
                        options = {f"{r['日時']} {r['place']} {r['item']} {r['amount']}円": r['id'] for _, r in user_df.iterrows()}
                        selected_del = st.selectbox("削除対象を選択", list(options.keys()), key=f"sel_{user_name}")
                        if st.button("この項目を削除", key=f"del_{user_name}"):
                            db.collection("expenses").document(options[selected_del]).delete()
                            st.rerun()

        show_history_compact(col1, "夫")
        show_history_compact(col2, "妻")
