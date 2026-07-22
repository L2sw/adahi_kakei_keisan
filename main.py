import os
import json
import base64
from io import BytesIO
import datetime
import pandas as pd
from PIL import Image, ImageOps
import streamlit as st
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore, storage

# ====================================================
# 1. ページ初期設定 & CSS
# ====================================================
st.set_page_config(
    page_title="家計簿共有",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ネオン風トースト通知などのスタイル
st.markdown("""
<style>
/* ポップアップ（トースト）スタイル */
.toast-container {
    position: fixed;
    top: 20px;
    right: 20px;
    z-index: 999999;
    display: flex;
    flex-direction: column;
    gap: 10px;
}
.toast-box {
    background: rgba(15, 23, 42, 0.9);
    border: 1px solid #38bdf8;
    box-shadow: 0 0 15px rgba(56, 189, 248, 0.4);
    border-radius: 8px;
    padding: 12px 16px;
    color: #f8fafc;
    font-family: sans-serif;
    min-width: 280px;
    animation: fadeIn 0.5s ease-in-out;
}
.toast-warning {
    border-color: #f43f5e;
    box-shadow: 0 0 15px rgba(244, 63, 94, 0.4);
}
.toast-title {
    font-weight: bold;
    font-size: 0.95rem;
    margin-bottom: 4px;
}
.toast-body {
    font-size: 0.85rem;
    color: #cbd5e1;
}
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
}
</style>
""", unsafe_allow_html=True)

# ====================================================
# 2. Firebase & Gemini API 初期化
# ====================================================
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        # secretsからキー情報を取得、または環境変数/ファイルから取得
        if "firebase" in st.secrets:
            fb_credentials = dict(st.secrets["firebase"])
            # private_key の改行コード調整
            if "private_key" in fb_credentials:
                fb_credentials["private_key"] = fb_credentials["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(fb_credentials)
            storage_bucket = st.secrets.get("firebase_storage_bucket", "")
            firebase_admin.initialize_app(cred, {
                'storageBucket': storage_bucket
            })
        else:
            # ローカル設定用フォールバック（必要に応じて設定）
            cred = credentials.Certificate("firebase_key.json")
            firebase_admin.initialize_app(cred)
    return firestore.client()

db = init_firebase()

# Gemini API の設定
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
elif "GEMINI_API_KEY" in os.environ:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# ====================================================
# 3. 共通関数 & セッション状態初期化
# ====================================================
@st.cache_data(ttl=5)
def get_data(collection_name):
    docs = db.collection(collection_name).stream()
    data = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        data.append(d)
    return data

def upload_image(file_bytes, doc_id):
    """Firebase Storage に画像をアップロードし署名付きURLを返す"""
    bucket = storage.bucket()
    blob = bucket.blob(f"receipts/{doc_id}.jpg")
    blob.upload_from_file(file_bytes, content_type="image/jpeg")
    # 1年間有効なURLを生成
    url = blob.generate_signed_url(expiration=datetime.timedelta(days=365))
    return url

# セッション状態の初期化
if "current_user" not in st.session_state:
    st.session_state.current_user = "大地"
if "gemini_items" not in st.session_state:
    st.session_state.gemini_items = None
if "gemini_place" not in st.session_state:
    st.session_state.gemini_place = ""
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# ====================================================
# 4. サイドバー・ユーザー切替
# ====================================================
st.sidebar.title("🏠 メニュー")
current_user = st.sidebar.radio("ログインユーザー", ["大地", "日向子"], index=0 if st.session_state.current_user == "大地" else 1)
st.session_state.current_user = current_user

menu = st.sidebar.radio("機能切り替え", [
    "台帳入力",
    "レシート撮影",
    "リスト管理",
    "月別集計・リセット",
    "管理者設定"
])

# ====================================================
# 5. メインページ分岐処理
# ====================================================

# ----------------------------------------------------
# A. 台帳入力 ページ
# ----------------------------------------------------
if menu == "台帳入力":
    st.header("📝 台帳入力 & レシートAI解析")

    # --- レシートAI解析セクション ---
    with st.expander("📷 レシート画像から自動入力 (Gemini AI)", expanded=False):
        uploaded_file = st.file_uploader(
            "レシート画像をアップロードしてください", 
            type=["jpg", "jpeg", "png"], 
            key=f"receipt_upload_{st.session_state.uploader_key}"
        )
        
        if uploaded_file is not None:
            img_bytes = uploaded_file.read()
            img_file = BytesIO(img_bytes)
            image = Image.open(img_file)
            image = ImageOps.exif_transpose(image) # 回転補正
            st.image(image, caption="アップロードされたレシート", width=300)

            if st.button("🤖 Geminiでレシートを解析する"):
                with st.spinner("AIが解析中...⚡"):
                    try:
                        # 長辺を1024pxにリサイズして軽量化
                        image.thumbnail((1024, 1024))
                        buffered = BytesIO()
                        image.save(buffered, format="JPEG", quality=85)
                        ai_img = Image.open(buffered)

                        model = genai.GenerativeModel("gemini-1.5-flash")
                        prompt = """
                        このレシート画像から「店舗名(place)」と「購入品目リスト(items)」を抽出してJSON形式で返してください。
                        JSONのフォーマット:
                        {
                          "place": "店名",
                          "items": [
                            {"item": "商品名1", "amount": 100},
                            {"item": "商品名2", "amount": 200}
                          ]
                        }
                        余計なマークダウンや説明テキストは含めず、純粋なJSON文字列のみを出力してください。
                        """
                        response = model.generate_content([prompt, ai_img])
                        cleaned_text = response.text.strip().replace("```json", "").replace("```", "").strip()
                        parsed_data = json.loads(cleaned_text)
                        
                        st.session_state.gemini_place = parsed_data.get("place", "")
                        
                        extracted_list = []
                        for row in parsed_data.get("items", []):
                            extracted_list.append({
                                "登録": True,
                                "場所": st.session_state.gemini_place,
                                "品目": row.get("item", ""),
                                "金額": int(row.get("amount", 0)),
                                "全立替": False
                            })
                        st.session_state.gemini_items = pd.DataFrame(extracted_list)
                        st.success("解析が完了しました！下のフォームで内容を確認・編集して登録してください。")
                    except Exception as e:
                        st.error(f"解析に失敗しました: {e}")

        # 解析結果の編集・取捨選択UI
        if st.session_state.gemini_items is not None and not st.session_state.gemini_items.empty:
            st.subheader("🛒 解析された項目の確認・取捨選択")
            st.write("不要な項目のチェックを外すか、内容を直接編集してから登録ボタンを押してください。")
            
            edited_df = st.data_editor(
                st.session_state.gemini_items,
                column_config={
                    "登録": st.column_config.CheckboxColumn("登録", default=True),
                    "場所": st.column_config.TextColumn("場所（店名）"),
                    "品目": st.column_config.TextColumn("品名"),
                    "金額": st.column_config.NumberColumn("金額 (円)", format="%d円"),
                    "全立替": st.column_config.CheckboxColumn("全立替", default=False)
                },
                hide_index=True,
                use_container_width=True
            )
            
            col_save, col_clear = st.columns(2)
            with col_save:
                if st.button("選択した項目を台帳に登録する💾", use_container_width=True):
                    with st.spinner("データを保存中...⏳"):
                        # レシート画像を Firebase Storage に保存しログを記録
                        doc_ref = db.collection("receipt_images").add({
                            "person": current_user,
                            "timestamp": firestore.SERVER_TIMESTAMP,
                            "image_url": ""
                        })
                        doc_id = doc_ref[1].id
                        
                        try:
                            img_file.seek(0)
                            image_url = upload_image(img_file, doc_id)
                            doc_ref[1].update({"image_url": image_url})
                        except Exception:
                            pass

                        # チェックされた各アイテムを expenses に登録
                        registered_count = 0
                        for _, row in edited_df.iterrows():
                            if row["登録"] and row["金額"] > 0:
                                db.collection("expenses").add({
                                    "person": current_user,
                                    "place": row["場所"] if row["場所"] else "不明",
                                    "item": row["品目"] if row["品目"] else "不明",
                                    "amount": int(row["金額"]),
                                    "is_reimburse": bool(row["全立替"]),
                                    "timestamp": firestore.SERVER_TIMESTAMP,
                                    "is_archived": False
                                })
                                registered_count += 1
                        
                        st.success(f"{registered_count}件の項目を台帳に登録しました！")
                        st.session_state.gemini_items = None
                        st.session_state.uploader_key += 1
                        st.cache_data.clear()
                        st.rerun()
                        
            with col_clear:
                if st.button("解析をやり直す（破棄）", use_container_width=True):
                    st.session_state.gemini_items = None
                    st.session_state.uploader_key += 1
                    st.rerun()

    # ----------------------------------------------------
    # 手入力による記録・精算結果・履歴一覧
    # ----------------------------------------------------
    cats = get_data("categories")
    df_cats = pd.DataFrame(cats) if cats else pd.DataFrame(columns=["place", "item"])
     
    if "place_sel" not in st.session_state: st.session_state.place_sel = ""

    with st.expander("🐔記録する", expanded=True):
        c1, c2 = st.columns(2)
        st.session_state.place_sel = c1.selectbox("場所選択", [""] + sorted(df_cats["place"].unique().tolist()) if not df_cats.empty else [""], 
                                                  label_visibility="collapsed", placeholder="場所選択🐎")
         
        available_items = df_cats[df_cats["place"] == st.session_state.place_sel]["item"].unique().tolist() if (not df_cats.empty and st.session_state.place_sel) else []
        sel_i = c2.selectbox("品目選択", [""] + available_items, label_visibility="collapsed", placeholder="品選択🍳")
         
        c3, c4 = st.columns(2)
        txt_p = c3.text_input("場所(直接入力)", label_visibility="collapsed", placeholder="場所(直入力)匙")
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
                if not udf.empty:
                    udf["日時"] = udf["timestamp"].dt.strftime("%-m/%-d %H:%M").fillna("-")
                    st.dataframe(udf[["日時", "place", "item", "amount", "is_reimburse"]].rename(columns={"place": "場所", "item": "品", "amount": "￥", "is_reimburse": "T"}), use_container_width=True, hide_index=True)
                    if u == current_user:
                        with st.expander("🍅 削除"):
                            opts = {f"{r['日時']} {r['place']} {r['item']} {r['amount']}円": r['id'] for _, r in udf.iterrows()}
                            sel = st.selectbox("選択", list(opts.keys()), key=f"sel_del_{u}")
                            if st.button("削除", key=f"del_{u}"):
                                db.collection("expenses").document(opts[sel]).delete()
                                st.cache_data.clear(); st.rerun()
                else:
                    st.info("データがありません。")
        show(c1, "大地"); show(c2, "日向子")

# ----------------------------------------------------
# B. その他のメニューページ
# ----------------------------------------------------
elif menu == "レシート撮影":
    st.header("📸 レシート撮影・履歴管理")
    receipts = get_data("receipt_images")
    if receipts:
        for r in receipts:
            st.write(f"投稿者: {r.get('person')} | 日時: {r.get('timestamp')}")
            if r.get("image_url"):
                st.image(r["image_url"], width=200)
    else:
        st.info("保存されたレシート画像はありません。")

elif menu == "リスト管理":
    st.header("🏷️ 場所・品目カテゴリの管理")
    c1, c2 = st.columns(2)
    new_p = c1.text_input("追加する場所（店名）")
    new_i = c2.text_input("追加する品目名")
    if st.button("カテゴリを追加"):
        if new_p and new_i:
            db.collection("categories").add({"place": new_p, "item": new_i})
            st.success("追加しました！")
            st.cache_data.clear()
            st.rerun()

elif menu == "月別集計・リセット":
    st.header("📊 月別集計・リセット")
    st.info("月別集計・リセット機能の画面です。")

elif menu == "管理者設定":
    st.header("⚙️ 管理者設定")
    st.info("管理者設定画面です。")
