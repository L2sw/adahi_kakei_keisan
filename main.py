import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json
import pandas as pd

# --- データベース接続 ---
key_dict = json.loads(st.secrets["textkey"])
creds = service_account.Credentials.from_service_account_info(key_dict)
db = firestore.Client(credentials=creds)

# --- パフォーマンス向上 ---
@st.cache_data(ttl=60)
def get_data(collection):
    docs = db.collection(collection).stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

# --- ページ設定 ---
st.set_page_config(page_title="2人だけの家計簿", page_icon="🦈", layout="wide")

# --- ユーザー判別 ---
params = st.query_params
user_code = params.get("user")
if isinstance(user_code, list): user_code = user_code[0]
current_user = "大地" if user_code == "h" else "日向子"

page = st.sidebar.radio("メニュー", ["台帳入力🐶", "リスト管理🐇", "月別集計・リセット🐻", "管理者設定🍖"])

# --- [機能1] リスト管理 ---
if page == "リスト管理🐇":
    st.header("🐖 リスト管理")
    if "last_place" not in st.session_state: st.session_state.last_place = ""
    with st.form("list_form"):
        place = st.text_input("場所🐡", value=st.session_state.last_place)
        item = st.text_input("品目🐧")
        if st.form_submit_button("登録🐤"):
            if place and item:
                cats = get_data("categories")
                if any(c["place"] == place and c["item"] == item for c in cats):
                    st.error("その場所と品目の組み合わせは既に登録されてるよ🦛")
                else:
                    db.collection("categories").add({"place": place, "item": item})
                    st.session_state.last_place = place
                    st.cache_data.clear()
                    st.rerun()
    st.write("---")
    cats = get_data("categories")
    if cats:
        df_cats = pd.DataFrame(cats).sort_values(by=["place", "item"])
        st.dataframe(df_cats[["place", "item"]].rename(columns={"place": "場所", "item": "品目"}), use_container_width=True, hide_index=True)
        with st.expander("🏺リストから削除🐸"):
            options = {f"{r['place']} - {r['item']}": r['id'] for _, r in df_cats.iterrows()}
            sel = st.selectbox("削除する項目を選択", list(options.keys()))
            if st.button("この項目を削除"):
                db.collection("categories").document(options[sel]).delete()
                st.cache_data.clear()
                st.rerun()

# --- [機能2] 月別集計・リセット ---
elif page == "月別集計・リセット🐻":
    st.header("🐻月支出・精算リセット")
    all_expenses = get_data("expenses")
    if all_expenses:
        df_all = pd.DataFrame(all_expenses)
        df_all["timestamp"] = pd.to_datetime([d.get("timestamp") if isinstance(d, dict) else d for d in df_all["timestamp"]], unit='s')
        df_all["month"] = df_all["timestamp"].dt.strftime("%Y年%m月")
        for month in sorted(df_all["month"].unique(), reverse=True):
            df_m = df_all[df_all["month"] == month]
            with st.expander(f"{month} (合計: {df_m['amount'].sum():,}円)"):
                st.dataframe(df_m[["person", "place", "item", "amount"]].rename(columns={"person": "担当", "place": "場所", "item": "品目", "amount": "金額(円)"}), use_container_width=True, hide_index=True)
    
    st.write("---")
    st.subheader("🐢精算リセット（両名の同意が必要）")
    consent_ref = db.collection("consent").document("status")
    status = consent_ref.get().to_dict() or {"daichi": False, "hinako": False}
    st.write(f"大地: {'✅' if status.get('daichi') else '❌'} | 日向子: {'✅' if status.get('hinako') else '❌'}")
    user_key = "daichi" if current_user == "大地" else "hinako"
    if st.button(f"同意切替🐦"):
        status[user_key] = not status.get(user_key, False)
        consent_ref.set(status)
        st.rerun()
    if status.get("daichi") and status.get("hinako"):
        if st.button("精算完了(アーカイブ)"):
            for doc in db.collection("expenses").where("is_archived", "==", False).stream(): doc.reference.update({"is_archived": True})
            consent_ref.set({"daichi": False, "hinako": False})
            st.cache_data.clear(); st.rerun()

# --- [機能4] 管理者設定(削除ページ) ---
elif page == "管理者設定🍖":
    st.header("🌎管理者設定（完全削除）")
    st.warning("この操作は取り消せません。両名の同意が必要です。")
    consent_ref = db.collection("consent").document("status")
    status = consent_ref.get().to_dict() or {"daichi": False, "hinako": False}
    all_expenses = get_data("expenses")
    
    st.write(f"現在の同意状況: 大地 {'✅' if status.get('daichi') else '❌'} / 日向子 {'✅' if status.get('hinako') else '❌'}")
    
    user_key = "daichi" if current_user == "大地" else "hinako"
    if st.button(f"自分の同意状態を切り替える (現在: {'✅' if status.get(user_key) else '❌'})"):
        status[user_key] = not status.get(user_key, False)
        consent_ref.set(status)
        st.rerun()
    
    confirm = st.checkbox("上記リスクを理解し、削除に同意します")
    if confirm and status.get("daichi") and status.get("hinako"):
        st.write("---")
        # 月別削除機能
        if all_expenses:
            df_all = pd.DataFrame(all_expenses)
            df_all["timestamp"] = pd.to_datetime([d.get("timestamp") if isinstance(d, dict) else d for d in df_all["timestamp"]], unit='s')
            df_all["month"] = df_all["timestamp"].dt.strftime("%Y年%m月")
            target_month = st.selectbox("削除したい年月を選択", sorted(df_all["month"].unique()))
            if st.button(f"【{target_month}】のデータをすべて削除する"):
                for _, row in df_all[df_all["month"] == target_month].iterrows():
                    db.collection("expenses").document(row["id"]).delete()
                consent_ref.set({"daichi": False, "hinako": False})
                st.cache_data.clear(); st.rerun()

        if st.button("【全データ】を完全に削除する"):
            for doc in db.collection("expenses").stream(): doc.reference.delete()
            consent_ref.set({"daichi": False, "hinako": False})
            st.cache_data.clear(); st.rerun()
        if st.button("【アーカイブ済み期間】のデータを完全に削除する"):
            for doc in db.collection("expenses").where("is_archived", "==", True).stream(): doc.reference.delete()
            consent_ref.set({"daichi": False, "hinako": False})
            st.cache_data.clear(); st.rerun()
    else:
        st.info("両名が同意し、チェックボックスをオンにするとボタンが有効になります。")

# --- [機能3] 家計簿入力 ---
else:
    st.markdown("## 🐘 2人だけの家計簿")
    cats = get_data("categories")
    df_cats = pd.DataFrame(cats) if cats else pd.DataFrame(columns=["place", "item"])
    with st.expander("🐔記録する", expanded=True):
        col1, col2 = st.columns(2)
        sel_p = col1.selectbox("場所選択", [""] + sorted(df_cats["place"].unique().tolist()))
        txt_p = col1.text_input("場所入力(優先)")
        place = txt_p if txt_p else sel_p
        sel_i = col2.selectbox("品目選択", [""] + (df_cats[df_cats["place"]==place]["item"].unique().tolist() if place in df_cats["place"].values else []))
        txt_i = col2.text_input("品目入力(優先)")
        item = txt_i if txt_i else sel_i
        with st.form("input_form", clear_on_submit=True):
            amount = st.number_input("金額(円)", value=None, min_value=0, step=1, format="%d")
            reimburse = st.checkbox("全立替")
            if st.form_submit_button("送信"):
                if amount and place and item:
                    db.collection("expenses").add({"person": current_user, "place": place, "item": item, "amount": int(amount), "is_reimburse": bool(reimburse), "timestamp": firestore.SERVER_TIMESTAMP, "is_archived": False})
                    st.cache_data.clear(); st.rerun()
    
    expenses = [e for e in get_data("expenses") if not e.get("is_archived", False)]
    if expenses:
        df = pd.DataFrame(expenses)
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)
        df["is_reimburse"] = df["is_reimburse"].fillna(False).astype(bool)
        df["timestamp"] = pd.to_datetime([d.get("timestamp") if isinstance(d, dict) else d for d in df["timestamp"]], unit='s')
        
        is_re = df["is_reimburse"]
        d_r = df[(df["person"] == "大地") & (is_re)]["amount"].sum()
        d_s = df[(df["person"] == "大地") & (~is_re)]["amount"].sum()
        h_r = df[(df["person"] == "日向子") & (is_re)]["amount"].sum()
        h_s = df[(df["person"] == "日向子") & (~is_re)]["amount"].sum()
        
        bal = (d_r + d_s / 2) - (h_r + h_s / 2)
        
        st.subheader("🐢 精算結果")
        if bal > 0: st.warning(f"💗 日向子から大地へ {int(bal):,} 円")
        elif bal < 0: st.warning(f"🐢 大地から日向子へ {int(abs(bal)):,} 円")
        else: st.success("貸し借りなし！")
        
        c1, c2 = st.columns(2)
        def show(c, u):
            with c:
                st.subheader(f"{u}の履歴")
                udf = df[df["person"]==u].copy()
                udf["日時"] = udf["timestamp"].dt.strftime("%m/%d %H:%M")
                st.dataframe(udf[["日時", "場所", "品", "額", "建替"]], use_container_width=True, hide_index=True)
                if u == current_user:
                    with st.expander("🍅 削除"): 
                        opts = {f"{r['日時']} {r['place']} {r['item']} {r['amount']}円": r['id'] for _, r in udf.iterrows()}
                        sel = st.selectbox("選択", opts.keys())
                        if st.button("削除", key=f"del_{u}"):
                            db.collection("expenses").document(opts[sel]).delete()
                            st.cache_data.clear(); st.rerun()
        show(c1, "大地"); show(c2, "日向子")
