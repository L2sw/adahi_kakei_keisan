import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
import json
import pandas as pd

# --- CSSでスマホ表示を強制的に調整 ---
st.markdown("""
    <style>
    /* フォーム内の各要素の余白を最小化 */
    .stTextInput > div > div > input, .stSelectbox > div > div > div {
        padding: 4px !important;
        min-height: 30px !important;
    }
    .stCheckbox { margin-top: 0px !important; }
    /* スマホでフォーム内カラムを横並びに強制 */
    [data-testid="column"] { width: 50% !important; flex: 0 0 50% !important; }
    /* 展開パネルの余白を詰める */
    .stExpander { margin-top: -10px !important; }
    </style>
    """, unsafe_allow_html=True)

# --- データベース接続 ---
key_dict = json.loads(st.secrets["textkey"])
creds = service_account.Credentials.from_service_account_info(key_dict)
db = firestore.Client(credentials=creds)

@st.cache_data(ttl=60)
def get_data(collection):
    docs = db.collection(collection).stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

st.set_page_config(page_title="2人だけの家計簿", page_icon="🦈", layout="wide")

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
        place = st.text_input("場所", value=st.session_state.last_place)
        item = st.text_input("品目")
        if st.form_submit_button("登録🐤"):
            if place and item:
                db.collection("categories").add({"place": place, "item": item})
                st.session_state.last_place = place
                st.cache_data.clear(); st.rerun()
    cats = get_data("categories")
    if cats:
        df_cats = pd.DataFrame(cats).sort_values(by=["place", "item"])
        st.dataframe(df_cats[["place", "item"]].rename(columns={"place": "場所", "item": "品目"}), use_container_width=True, hide_index=True)

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
            with st.expander(f"{month} ({df_m['amount'].sum():,}円)"):
                st.dataframe(df_m[["person", "place", "item", "amount"]].rename(columns={"person": "担当", "place": "場所", "item": "品目", "amount": "金額"}), use_container_width=True, hide_index=True)
    
    st.write("---")
    st.subheader("🐢精算リセット")
    consent_ref = db.collection("consent").document("status")
    status = consent_ref.get().to_dict() or {"daichi": False, "hinako": False}
    user_key = "daichi" if current_user == "大地" else "hinako"
    if st.button("同意切替"):
        status[user_key] = not status.get(user_key, False)
        consent_ref.set(status)
        st.rerun()
    if status.get("daichi") and status.get("hinako"):
        if st.button("精算完了(アーカイブ)"):
            for doc in db.collection("expenses").where("is_archived", "==", False).stream(): doc.reference.update({"is_archived": True})
            consent_ref.set({"daichi": False, "hinako": False})
            st.cache_data.clear(); st.rerun()

# --- [機能4] 管理者設定 ---
elif page == "管理者設定🍖":
    st.header("🌎管理者設定")
    consent_ref = db.collection("consent").document("status")
    status = consent_ref.get().to_dict() or {"daichi": False, "hinako": False}
    user_key = "daichi" if current_user == "大地" else "hinako"
    if st.button(f"同意切替 (現在:{'✅' if status.get(user_key) else '❌'})"):
        status[user_key] = not status.get(user_key, False)
        consent_ref.set(status)
        st.rerun()
    confirm = st.checkbox("上記リスクを理解し、削除に同意します")
    if confirm and status.get("daichi") and status.get("hinako"):
        all_expenses = get_data("expenses")
        if all_expenses:
            df_all = pd.DataFrame(all_expenses)
            df_all["timestamp"] = pd.to_datetime([d.get("timestamp") if isinstance(d, dict) else d for d in df_all["timestamp"]], unit='s')
            df_all["month"] = df_all["timestamp"].dt.strftime("%Y年%m月")
            target = st.selectbox("削除年月", sorted(df_all["month"].unique()))
            if st.button(f"{target} 削除"):
                for _, r in df_all[df_all["month"] == target].iterrows(): db.collection("expenses").document(r["id"]).delete()
                consent_ref.set({"daichi": False, "hinako": False}); st.rerun()
        if st.button("【全データ削除】"):
            for doc in db.collection("expenses").stream(): doc.reference.delete()
            consent_ref.set({"daichi": False, "hinako": False}); st.rerun()

# --- [機能3] 家計簿入力 ---
else:
    st.markdown("## 🐘 家計簿")
    cats = get_data("categories")
    df_cats = pd.DataFrame(cats) if cats else pd.DataFrame(columns=["place", "item"])
    
    with st.expander("🐔記録", expanded=True):
        with st.form("input_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            sel_p = c1.selectbox("場所S", [""] + sorted(df_cats["place"].unique().tolist()), label_visibility="collapsed")
            txt_p = c2.text_input("場所D", placeholder="場所直接", label_visibility="collapsed")
            
            p = txt_p if txt_p else sel_p
            c3, c4 = st.columns(2)
            sel_i = c3.selectbox("品目S", [""] + (df_cats[df_cats["place"]==p]["item"].unique().tolist() if p in df_cats["place"].values else []), label_visibility="collapsed")
            txt_i = c4.text_input("品目D", placeholder="品目直接", label_visibility="collapsed")
            
            c5, c6 = st.columns([2, 1])
            amount = c5.number_input("金額", placeholder="金額", label_visibility="collapsed")
            reimburse = c6.checkbox("立替")
            
            if st.form_submit_button("送信"):
                if amount and p and (txt_i if txt_i else sel_i):
                    db.collection("expenses").add({"person": current_user, "place": p, "item": txt_i if txt_i else sel_i, "amount": int(amount), "is_reimburse": bool(reimburse), "timestamp": firestore.SERVER_TIMESTAMP, "is_archived": False})
                    st.cache_data.clear(); st.rerun()
    
    expenses = [e for e in get_data("expenses") if not e.get("is_archived", False)]
    if expenses:
        df = pd.DataFrame(expenses)
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)
        df["timestamp"] = pd.to_datetime([d.get("timestamp") if isinstance(d, dict) else d for d in df["timestamp"]], unit='s')
        
        is_re = df["is_reimburse"].fillna(False)
        bal = (df[(df["person"] == "大地") & (is_re)]["amount"].sum() + df[(df["person"] == "大地") & (~is_re)]["amount"].sum()/2) - \
              (df[(df["person"] == "日向子") & (is_re)]["amount"].sum() + df[(df["person"] == "日向子") & (~is_re)]["amount"].sum()/2)
        
        if bal > 0: st.warning(f"💗 日向子→大地: {int(bal):,}円")
        elif bal < 0: st.warning(f"🐢 大地→日向子: {int(abs(bal)):,}円")
        
        c1, c2 = st.columns(2)
        for c, u in zip([c1, c2], ["大地", "日向子"]):
            with c:
                st.subheader(u)
                udf = df[df["person"]==u].copy()
                udf["日時"] = udf["timestamp"].dt.strftime("%m/%d")
                st.dataframe(udf[["日時", "place", "item", "amount"]], use_container_width=True, hide_index=True)
                if u == current_user:
                    opts = {f"{r['日時']} {r['place']} {r['amount']}円": r['id'] for _, r in udf.iterrows()}
                    sel = st.selectbox("削除対象", opts.keys(), label_visibility="collapsed", key=f"sel_{u}")
                    if st.button(f"削除({u})", key=f"btn_{u}"):
                        db.collection("expenses").document(opts[sel]).delete(); st.cache_data.clear(); st.rerun()
