import streamlit as st
from google.cloud import firestore
from google.cloud import storage
from google.oauth2 import service_account
import json
import pandas as pd
from PIL import Image, ImageOps
import io
from datetime import datetime, date, timedelta
import streamlit.components.v1 as components

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
    """スマホ純正の超高画質を維持し、かつ縦横の回転を正しく補正してFirebaseに保存する"""
    img = Image.open(image_file)
    
    # スマホ特有の回転情報（EXIF）を解析し、撮影した通りの向きに自動補正
    img = ImageOps.exif_transpose(img)
    
    # スマホカメラの超高画質をそのまま活かすため、リサイズ上限を3000pxに引き上げ
    img.thumbnail((3000, 3000))
    
    output = io.BytesIO()
    # 最高画質品質（quality=98）で圧縮をほぼゼロにして保存
    img.save(output, format="JPEG", quality=98)
    output.seek(0)
    
    blob = bucket.blob(f"receipts/{doc_id}.jpg")
    blob.upload_from_file(output, content_type="image/jpeg")
    
    return blob.generate_signed_url(version="v4", expiration=timedelta(days=7), method="GET")

def delete_image(doc_id):
    """Firebase Storage上の画像を削除する"""
    blob = bucket.blob(f"receipts/{doc_id}.jpg")
    if blob.exists():
        blob.delete()

# --- ページ設定 ---
st.set_page_config(page_title="2人だけの台帳", page_icon="🦈", layout="wide")

# 表示の間隔をギリギリまで詰めるためのカスタムCSS & ポップアップ（st.toast）のド派手化CSS
st.markdown("""
    <style>
        [data-testid="stExpander"] {
            margin-bottom: 4px !important;
            padding-bottom: 0px !important;
        }
        [data-testid="stExpanderDetails"] {
            padding: 8px 12px !important;
        }
        .element-container {
            margin-bottom: 4px !important;
        }
        h3 {
            margin-top: 4px !important;
            margin-bottom: 4px !important;
            padding-bottom: 0px !important;
        }
        [data-testid="stFileUploader"] {
            margin-bottom: 15px !important;
        }
        
        /* 🚨 ド派手なポップアップ（st.toast）CSSカスタム */
        div[data-testid="stToast"] {
            background-color: #111111 !important;
            border: 3px solid #FF0055 !important;
            box-shadow: 0px 0px 20px #FF0055 !important;
            color: #FFFFFF !important;
            font-size: 16px !important;
            font-weight: bold !important;
            border-radius: 12px !important;
            padding: 12px 20px !important;
        }
        div[data-testid="stToast"] p {
            font-size: 16px !important;
            color: #FFFF00 !important;
            text-shadow: 1px 1px 2px #000;
        }
    </style>
""", unsafe_allow_html=True)

# --- ユーザー判別 ---
params = st.query_params
user_code = params.get("user")
if isinstance(user_code, list): user_code = user_code[0]
current_user = "大地" if user_code == "h" else "日向子"

# --- 🔔 全ページ共通：期限直前・超過ToDoのポップアップ通知チェック ---
if "todo_alert_shown" not in st.session_state:
    st.session_state.todo_alert_shown = False

if not st.session_state.todo_alert_shown:
    all_todos = get_data("todos")
    if all_todos:
        today = date.today()
        overdue_list = []
        due_soon_list = []
        
        for t in all_todos:
            due_str = t.get("due_date")
            content = t.get("content", "名称未設定")
            if due_str:
                try:
                    due_dt = datetime.strptime(due_str, "%Y-%m-%d").date()
                    days_left = (due_dt - today).days
                    if days_left < 0:
                        overdue_list.append(f"💥{content}({due_str})")
                    elif 0 <= days_left <= 1:
                        due_soon_list.append(f"⚡{content}({due_str})")
                except ValueError:
                    pass

        # 期限切れがあればド派手警告ポップアップ
        if overdue_list:
            st.toast(f"🚨【超危険・期限切れ】\n" + " / ".join(overdue_list), icon="🚨")
        # 期限直前（今日・明日）があればド派手注意ポップアップ
        if due_soon_list:
            st.toast(f"🔥【緊急・今日明日の期限】\n" + " / ".join(due_soon_list), icon="⏰")

        if overdue_list or due_soon_list:
            # ⏱️ JavaScriptで表示時間を10秒間（10000ms）に延長する処理
            components.html("""
                <script>
                    setTimeout(function() {
                        var toasts = window.parent.document.querySelectorAll('div[data-testid="stToast"]');
                        toasts.forEach(function(toast) {
                            toast.style.transition = 'opacity 0.5s ease';
                            toast.style.opacity = '0';
                            setTimeout(function() { toast.remove(); }, 500);
                        });
                    }, 10000);
                </script>
            """, height=0, width=0)

    st.session_state.todo_alert_shown = True

# メニュー設定
page = st.sidebar.radio("🐭🐄🐯🐍 メメニュー 🐏🐗🐒🐩", ["台帳入力🐶", "レシート撮影📷", "リスト管理🐇", "ToDoリスト📝", "月別集計・リセット🐻", "管理者設定🍖"])

# --- レシート撮影ページ ---
if page == "レシート撮影📷":
    st.header("📸 パシャる💩")
    
    # 🛠️ 連続撮影対応のための仕掛け：動的な一意のキー、またはセッションステートで制御するために key を指定
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0

    img_file = st.file_uploader(
        "ここをタップしてレシートを撮影 📸", 
        type=["jpg", "jpeg", "png"],
        label_visibility="collapsed",
        key=f"receipt_uploader_{st.session_state.uploader_key}"  # 保存後にこのキーを変えることで完全にクリアします
    )
    
    if img_file is not None:
        # プレビュー表示時も、撮影した通りの正しい向きで表示させる
        preview_img = Image.open(img_file)
        preview_img = ImageOps.exif_transpose(preview_img)
        
        st.image(preview_img, caption="選択されたレシート", use_container_width=True)
        st.success("写真の準備ができました！保存する場合は下のボタンを押してください。")
        
        if st.button("このレシート画像を保存する💾", use_container_width=True):
            with st.spinner("正しい向きに補正してアップロード中...⏳"):
                doc_ref = db.collection("receipt_images").add({
                    "person": current_user,
                    "timestamp": firestore.SERVER_TIMESTAMP,
                    "image_url": ""
                })
                doc_id = doc_ref[1].id
                
                image_url = upload_image(img_file, doc_id)
                doc_ref[1].update({"image_url": image_url})
                
                st.success("保存が完了しました！")
                
                # 🛠️ 【クリア処理】アップローダーのキーをインクリメント（変更）することで、
                # 選択されていたファイルやプレビュー表示を完全に消去し、初期状態に戻します。
                st.session_state.uploader_key += 1
                
                st.cache_data.clear()
                st.rerun()
    
    # 🛠️ 【新機能】ログイン中のユーザーに応じた「自分のレシート全削除機能」
    st.subheader(f"🥎レシート一括削除")
    st.write(f"自分が撮影したレシートのみをすべて削除できるよ蜥")
    
    confirm_all_del = st.checkbox(f"🚙本当に【{current_user}】のレシートを全削除する？栗")
    if st.button(f"🚨 {current_user}のを全削除する", use_container_width=True, disabled=not confirm_all_del):
        with st.spinner(f"{current_user}のデータを一括削除中...⏳"):
            # ログイン中のユーザーのレシートのみを取得
            my_receipts = db.collection("receipt_images").where("person", "==", current_user).stream()
            deleted_count = 0
            for doc in my_receipts:
                # Storageの画像ファイルを削除
                delete_image(doc.id)
                # Firestoreのドキュメントを削除
                doc.reference.delete()
                deleted_count += 1
            
            if deleted_count > 0:
                st.success(f"{deleted_count}件のレシートをすべて削除したよ！")
            else:
                st.info("削除するレシートがありませんでした。")
            st.cache_data.clear()
            st.rerun()

    # 保存された画像の取得と一覧表示
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
        
        df_daichi = df_receipts[df_receipts["person"] == "大地"]
        df_hinako = df_receipts[df_receipts["person"] == "日向子"]
        
        col_d, col_h = st.columns(2)
        
        # --- 大地の画像履歴 ---
        with col_d:
            st.markdown("### 🐄大地レシート")
            if not df_daichi.empty:
                for _, r in df_daichi.iterrows():
                    label = f"🐔 {r['日時']}"
                    with st.expander(label):
                        if r["image_url"]:
                            st.image(r["image_url"], use_container_width=True)
                            if st.button("🐛削除", key=f"del_{r['id']}"):
                                with st.spinner("削除中...⏳"):
                                    delete_image(r["id"])
                                    db.collection("receipt_images").document(r["id"]).delete()
                                    st.success("削除したよ")
                                    st.cache_data.clear()
                                    st.rerun()
                        else:
                            st.info("画像URLがありません。")
            else:
                st.info("✏大地のパシャlogはないよ")
                
        # --- 日向子の画像履歴 ---
        with col_h:
            st.markdown("### 🐇日向子レシート")
            if not df_hinako.empty:
                for _, r in df_hinako.iterrows():
                    label = f"🐥 {r['日時']}"
                    with st.expander(label):
                        if r["image_url"]:
                            st.image(r["image_url"], use_container_width=True)
                            if st.button("🐼削除", key=f"del_{r['id']}"):
                                with st.spinner("削除中...⏳"):
                                    delete_image(r["id"])
                                    db.collection("receipt_images").document(r["id"]).delete()
                                    st.success("削除したよ☄")
                                    st.cache_data.clear()
                                    st.rerun()
                        else:
                            st.info("画像URLがありません。")
            else:
                st.info("💗日向子のパシャlogはないよ")
    else:
        st.info("まだ保存されたレシートはありません。")

# --- リスト管理 ---
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

# --- ToDoリスト ---
elif page == "🍋ToDoリスト🍋":
    st.header("💀 ToDoリスト")

    # ToDo一覧の取得と表示（超コンパクト化）
    todos = get_data("todos")
    if todos:
        df_todos = pd.DataFrame(todos)
        df_todos["due_date_dt"] = pd.to_datetime(df_todos["due_date"], errors="coerce")
        df_todos = df_todos.sort_values(by="due_date_dt", ascending=True)

        today = date.today()

        for _, todo in df_todos.iterrows():
            todo_id = todo["id"]
            person = todo.get("person", "不明")
            content = todo.get("content", "")
            due_str = todo.get("due_date", "未設定")

            due_dt = todo["due_date_dt"].date() if pd.notnull(todo["due_date_dt"]) else None
            days_left = (due_dt - today).days if due_dt else None

            if days_left is not None:
                if days_left < 0:
                    badge = f"🚨 期限切({abs(days_left)}日超)"
                elif days_left == 0:
                    badge = "⏰ 今日まで"
                elif days_left == 1:
                    badge = "⚠️ 明日まで"
                else:
                    badge = f"📅 あと{days_left}日"
            else:
                badge = ""

            # 1行にまとめた超コンパクトカードレイアウト
            c_badge, c_text, c_del = st.columns([1.2, 3.8, 1])
            with c_badge:
                st.caption(f"**{badge}**")
            with c_text:
                st.write(f"**{content}** `(by {person} / 期限: {due_str})`")
            with c_del:
                if st.button("完了✨", key=f"todo_del_{todo_id}", use_container_width=True):
                    db.collection("todos").document(todo_id).delete()
                    st.cache_data.clear()
                    st.rerun()
    else:
        st.info("現在ToDoはありません！平和です🎉")

    st.write("---")

    # ② 下部：新規ToDo追加フォーム
    with st.expander("➕ 新しいToDoを追加する", expanded=False):
        with st.form("add_todo_form"):
            c_input, c_date = st.columns([3, 1])
            todo_content = c_input.text_input("やる事の内容", placeholder="例：電気代の支払い、ゴミ出し など")
            due_date = c_date.date_input("期限", value=date.today() + timedelta(days=1))
            submit_todo = st.form_submit_button("ToDoを追加⚡", use_container_width=True)
            
            if submit_todo:
                if todo_content.strip():
                    db.collection("todos").add({
                        "person": current_user,
                        "content": todo_content.strip(),
                        "due_date": due_date.strftime("%Y-%m-%d")
                    })
                    st.success("追加完了！")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("内容を入力してください！")

# --- 月別集計・リreset ---
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
    st.subheader("🐢精算reset（2人の同意が必要だどん）")
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

# --- 管理者設定(削除ページ) ---
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

# --- 家計簿入力 (台帳入力) ---
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
