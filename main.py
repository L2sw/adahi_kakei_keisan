import streamlit as st
from google.cloud import firestore
from google.cloud import storage
from google.oauth2 import service_account
import json
import pandas as pd
from PIL import Image
import io

# --- データベース・ストレージ接続 ---
key_dict = json.loads(st.secrets["textkey"])
creds = service_account.Credentials.from_service_account_info(key_dict)
db = firestore.Client(credentials=creds)

# ★★★ Firebase Storageの設定 ★★★
BUCKET_NAME = "kakei-adachi.firebasestorage.app"
storage_client = storage.Client(credentials=creds)
bucket = storage_client.bucket(BUCKET_NAME)

# --- パフォーマンス向上 ---
@st.cache_data(ttl=60)
def get_data(collection):
    docs = db.collection(collection).stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

# --- 画像処理用の関数 ---
def upload_image(image_file, doc_id):
    """画像を圧縮してFirebase Storageにアップロードし、URLを返す"""
    img = Image.open(image_file)
    img.thumbnail((1024, 1024))  # 容量節約のため最大1024pxにリサイズ
    
    output = io.BytesIO()
    img.save(output, format="JPEG", quality=80)
    output.seek(0)
    
    blob = bucket.blob(f"receipts/{doc_id}.jpg")
    blob.upload_from_file(output, content_type="image/jpeg")
    
    # 30日間有効な署名付きURLを発行
    return blob.generate_signed_url(expiration=30*24*60*60)

def delete_image(doc_id):
    """Firebase Storage上の画像を削除する"""
    blob = bucket.blob(f"receipts/{doc_id}.jpg")
    if blob.exists():
        blob.delete()

# --- ページ設定 ---
st.set_page_config(page_title="2人だけの台帳", page_icon="🦈", layout="wide")

# --- ユーザー判別 ---
params = st.query_params
user_code = params.get("user")
if isinstance(user_code, list): user_code = user_code[0]
current_user = "大地" if user_code == "h" else "日向子"

# ★★★ メニューに「レシート撮影📷」を新しく追加しました ★★★
page = st.sidebar.radio("🐭🐄🐯🐍 メニュー 🐏🐗🐒🐩", ["台帳入力🐶", "レシート撮影📷", "リスト管理🐇", "月別集計・リセット🐻", "管理者設定🍖"])

# --- [新規ページ] レシート撮影 ---
if page == "レシート撮影📷":
    st.header("📷 レシート撮影・管理")
    st.write("ここで撮影したレシートは、下の履歴からいつでも確認・削除ができます。")
    
    # 1. 撮影エリア
    img_file = st.camera_input("レシートをパシャリ（納得いくまで撮り直しできます）")
    
    if img_file is not None:
        st.success("写真が準備できました！保存する場合は下のボタンを押してください。")
        if st.button("このレシート画像を保存する💾", use_container_width=True):
            with st.spinner("画像をアップロード中...⏳"):
                # データベースに画像管理用の専用レコードを作成
                doc_ref = db.collection("receipt_images").add({
                    "person": current_user,
                    "timestamp": firestore.SERVER_TIMESTAMP,
                    "image_url": ""
                })
                doc_id = doc_ref[1].id
                
                # 画像をストレージに保存してURLを更新
                image_url = upload_image(img_file, doc_id)
                doc_ref[1].update({"image_url": image_url})
                
                st.success("保存が完了しました！")
                st.cache_data.clear()
                st.rerun()
                
    st.write("---")
    st.subheader("🗂️ 保存されたレシート履歴")
    
    # 2. 保存された画像の取得と一覧表示
    # ※リアルタイムに近い状態で確認できるよう、この一覧はキャッシュ(get_data)を使わず直接取得します
    receipt_docs = db.collection("receipt_images").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    receipts = [{"id": doc.id, **doc.to_dict()} for doc in receipt_docs]
    
    if receipts:
        df_receipts = pd.DataFrame(receipts)
        
        # タイムゾーン変換処理
        timestamps = [d.get("timestamp") if isinstance(d, dict) else d for d in df_receipts["timestamp"]]
        df_receipts["timestamp"] = pd.to_datetime(timestamps, errors='coerce')
        if df_receipts["timestamp"].dt.tz is None:
            df_receipts["timestamp"] = df_receipts["timestamp"].dt.tz_localize('UTC')
        df_receipts["timestamp"] = df_receipts["timestamp"].dt.tz_convert('Asia/Tokyo')
        df_receipts["日時"] = df_receipts["timestamp"].dt.strftime("%Y/%m/%d %H:%M").fillna("-")
        
        # 閲覧・削除用の選択肢を作成
        img_opts = {}
        for _, r in df_receipts.iterrows():
            label = f"{r['日時']} ({r['person']}が撮影)"
            img_opts[label] = {"id": r["id"], "url": r["image_url"]}
            
        sel_label = st.selectbox("確認・削除したいレシートを選択してください", list(img_opts.keys()))
        
        if sel_label:
            selected_data = img_opts[sel_label]
            
            # 画像の表示
            if selected_data["url"]:
                st.image(selected_data["url"], caption=sel_label, use_container_width=True)
            else:
                st.info("画像の処理中、またはURLがありません。")
                
            # 不要な場合の削除機能
            st.write("---")
            with st.expander("🗑️ このレシートを削除する"):
                st.warning("この操作を行うと、画像データは完全に消去されます。")
                if st.button("完全に削除する", key="del_receipt_btn"):
                    with st.spinner("削除中...⏳"):
                        delete_image(selected_data["id"])  # Storageから削除
                        db.collection("receipt_images").document(selected_data["id"]).delete()  # Firestoreから削除
                        st.success("削除しました。")
                        st.cache_data.clear()
                        st.rerun()
    else:
        st.info("まだ保存されたレシートはありません。")

# --- [機能1] リスト管理 ---
elif page == "リスト管理🐇":
    st.header("🐖 リスト管理")
    if "last_place" not in st.session_state: st.session_state.last_place = ""
    with st.form("list_form"):
        place = st.text_input("場所🐡", value=st.session_state.last_place)
        item = st.text_input("品🐧")
        if st.form_submit_button("登録🐤"):
            if place and item:
                cats = get_data("categories")
                if any(c["place"] == place and c["item"] == item for c in cats):
                    st.error("その場所と品の組み合わせは既に登録されてるよ🦛")
                else:
                    db.collection("categories").add({"place": place, "item": item})
                    st.session_state.last_place = place
                    st.cache_data.clear()
                    st.rerun()
    st.write("---")
    cats = get_data("categories")
    if cats:
        df_cats = pd.DataFrame(cats).sort_values(by=["place", "item"])
        st.dataframe(df_cats[["place", "item"]].rename(columns={"place": "場所", "item": "品"}), use_container_width=True, hide_index=True)
        with st.expander("🏺リストから削除🐸"):
            options = {f"{r['place']} - {r['item']}": r['id'] for _, r in df_cats.iterrows()}
            sel = st.selectbox("削除する項目を選択", list(options.keys()))
            if st.button("この項目を削除"):
                db.collection("categories").document(options[sel]).delete()
                st.cache_data.clear()
                st.rerun()

# --- [機能2] 月別集計・リセット ---
elif page == "月別集計・リセット🐻":
    st.header("🐻月支出")
    all_expenses = get_data("expenses")
    if all_expenses:
        df_all = pd.DataFrame(all_expenses)
        timestamps = [d.get("timestamp") if isinstance(d, dict) else d for d in df_all["timestamp"]]
        df_all["timestamp"] = pd.to_datetime(timestamps, errors='coerce')
        if df_all["timestamp"].dt.tz is None:
            df_all["timestamp"] = df_all["timestamp"].dt.tz_localize('UTC')
        df_all["timestamp"] = df_all["timestamp"].dt.tz_convert('Asia/Tokyo')
        
        df_all["month"] = df_all["timestamp"].dt.strftime("%Y年%m月")
        for month in sorted(df_all["month"].dropna().unique(), reverse=True):
            df_m = df_all[df_all["month"] == month]
            with st.expander(f"{month} (合計: {df_m['amount'].sum():,}円)"):
                st.dataframe(df_m[["person", "place", "item", "amount"]].rename(columns={"person": "誰", "place": "場所", "item": "品", "amount": "￥"}), use_container_width=True, hide_index=True)
     
    st.write("---")
    st.subheader("🐢精算リセット（2人の同意が必要だどん）")
    consent_ref = db.collection("consent").document("status")
    status = consent_ref.get().to_dict() or {"daichi": False, "hinako": False}
    st.write(f"大地: {'👼' if status.get('daichi') else '💀'} | 日向子: {'👼' if status.get('hinako') else '💀'}")
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
     
    st.write(f"現在の同意状況: 大地 {'👼' if status.get('daichi') else '💀'} / 日向子 {'👼' if status.get('hinako') else '💀'}")
     
    user_key = "daichi" if current_user == "大地" else "hinako"
    if st.button(f"自分の同意状態を切り替える (現在: {'👼' if status.get(user_key) else '💀'})"):
        status[user_key] = not status.get(user_key, False)
        consent_ref.set(status)
        st.rerun()
     
    confirm = st.checkbox("上記リスクを理解し、削除に同意します")
    if confirm and status.get("daichi") and status.get("hinako"):
        st.write("---")
        if all_expenses:
            df_all = pd.DataFrame(all_expenses)
            timestamps = [d.get("timestamp") if isinstance(d, dict) else d for d in df_all["timestamp"]]
            df_all["timestamp"] = pd.to_datetime(timestamps, errors='coerce')
            if df_all["timestamp"].dt.tz is None:
                df_all["timestamp"] = df_all["timestamp"].dt.tz_localize('UTC')
            df_all["timestamp"] = df_all["timestamp"].dt.tz_convert('Asia/Tokyo')
            
            df_all["month"] = df_all["timestamp"].dt.strftime("%Y年%m月")
            target_month = st.selectbox("削除したい年月を選択", sorted(df_all["month"].dropna().unique()))
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

# --- [機能3] 家計簿入力 (台帳入力) ---
else:
    st.markdown("## 🐘 2人だけの台帳")
    cats = get_data("categories")
    df_cats = pd.DataFrame(cats) if cats else pd.DataFrame(columns=["place", "item"])
     
    if "place_sel" not in st.session_state: st.session_state.place_sel = ""

    with st.expander("🐔記録する", expanded=True):
        c1, c2 = st.columns(2)
        st.session_state.place_sel = c1.selectbox("場所選択", [""] + sorted(df_cats["place"].unique().tolist()), 
                                                   label_visibility="collapsed", placeholder="場所選択🐎")
         
        available_items = df_cats[df_cats["place"] == st.session_state.place_sel]["item"].unique().tolist() if st.session_state.place_sel else []
        sel_i = c2.selectbox("品目選択", [""] + available_items, label_visibility="collapsed", placeholder="品選択🍳")
         
        c3, c4 = st.columns(2)
        txt_p = c3.text_input("場所(直接入力)", label_visibility="collapsed", placeholder="場所(直入力)🥄")
        txt_i = c4.text_input("品目(直接入力)", label_visibility="collapsed", placeholder="品(直入力)🥬")
         
        c5, c6 = st.columns([2, 1])
        amount = c5.number_input("金額(円)", value=None, min_value=0, step=1, format="%d", label_visibility="collapsed", placeholder="￥🌲")
        reimburse = c6.checkbox("全立替")
         
        if st.button("送信⚡"):
            place = txt_p if txt_p else st.session_state.place_sel
            item = txt_i if txt_i else sel_i
            if amount and place and item:
                db.collection("expenses").add({"person": current_user, "place": place, "item": item, "amount": int(amount), "is_reimburse": bool(reimburse), "timestamp": firestore.SERVER_TIMESTAMP, "is_archived": False})
                st.session_state.place_sel = ""
                st.cache_data.clear(); st.rerun()

    expenses = [e for e in get_data("expenses") if not e.get("is_archived", False)]
    if expenses:
        df = pd.DataFrame(expenses)
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)
        df["is_reimburse"] = df["is_reimburse"].fillna(False).astype(bool)
        
        timestamps = [d.get("timestamp") if isinstance(d, dict) else d for d in df["timestamp"]]
        df["timestamp"] = pd.to_datetime(timestamps, errors='coerce')
        if df["timestamp"].dt.tz is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize('UTC')
        df["timestamp"] = df["timestamp"].dt.tz_convert('Asia/Tokyo')
         
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
                st.subheader(f"{u}log🍄")
                udf = df[df["person"]==u].copy()
                udf["日時"] = udf["timestamp"].dt.strftime("%-m/%-d %H:%M").fillna("-")
                st.dataframe(udf[["日時", "place", "item", "amount", "is_reimburse"]].rename(columns={"place": "場所", "item": "品", "amount": "￥", "is_reimburse": "T"}), use_container_width=True, hide_index=True)
                if u == current_user:
                    with st.expander("🍅 削除"):
                        opts = {f"{r['日時']} {r['place']} {r['item']} {r['amount']}円": r['id'] for _, r in udf.iterrows()}
                        sel = st.selectbox("選択", opts.keys(), key=f"sel_del_{u}")
                        if st.button("削除", key=f"del_{u}"):
                            db.collection("expenses").document(opts[sel]).delete()
                            st.cache_data.clear(); st.rerun()
        show(c1, "大地"); show(c2, "日向子")
