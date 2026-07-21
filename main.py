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
import google.generativeai as genai

# --- データベース・ストレージ接続 ---
key_dict = json.loads(st.secrets["textkey"])
creds = service_account.Credentials.from_service_account_info(key_dict)
db = firestore.Client(credentials=creds)

# --- Gemini APIの設定 ---
genai.configure(api_key=st.secrets.get("GEMINI_API_KEY", ""))

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
    img = ImageOps.exif_transpose(img)
    img.thumbnail((3000, 3000))
    
    output = io.BytesIO()
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

# 表示の間隔を調整するためのカスタムCSS
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
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] {
            margin-bottom: 8px !important;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] > label {
            padding-top: 10px !important;
            padding-bottom: 10px !important;
            margin-bottom: 4px !important;
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
                        overdue_list.append(f"💥 {content} ({due_str})")
                    elif 0 <= days_left <= 1:
                        due_soon_list.append(f"⚡ {content} ({due_str})")
                except ValueError:
                    pass

        if overdue_list or due_soon_list:
            popup_html = ""
            if overdue_list:
                popup_html += "<div style='color: #FF0055; font-weight: bold; font-size: 17px; margin-bottom: 8px;'>🚨【超危険・期限切れ】</div>"
                for item in overdue_list:
                    popup_html += f"<div style='color: #FFFF00; font-size: 15px; margin-bottom: 4px;'>・{item}</div>"
            
            if due_soon_list:
                if overdue_list:
                    popup_html += "<div style='margin-top: 12px;'></div>"
                popup_html += "<div style='color: #FF9900; font-weight: bold; font-size: 17px; margin-bottom: 8px;'>🔥【緊急・今日明日の期限】</div>"
                for item in due_soon_list:
                    popup_html += f"<div style='color: #FFFF00; font-size: 15px; margin-bottom: 4px;'>・{item}</div>"

            components.html(f"""
                <script>
                    var doc = window.parent.document;
                    var oldToast = doc.getElementById('custom-neon-toast');
                    if (oldToast) oldToast.remove();

                    var toast = doc.createElement('div');
                    toast.id = 'custom-neon-toast';
                    toast.innerHTML = `{popup_html}`;
                    
                    Object.assign(toast.style, {{
                        position: 'fixed',
                        top: '20%',
                        left: '50%',
                        transform: 'translateX(-50%)',
                        backgroundColor: '#111111',
                        border: '3.5px solid #FF0055',
                        boxShadow: '0px 0px 30px #FF0055',
                        borderRadius: '16px',
                        padding: '20px 24px',
                        zIndex: '999999',
                        minWidth: '300px',
                        maxWidth: '85vw',
                        maxHeight: '70vh',
                        overflowY: 'auto',
                        fontFamily: 'sans-serif',
                        opacity: '0',
                        transition: 'opacity 0.5s ease',
                        pointerEvents: 'none'
                    }});

                    doc.body.appendChild(toast);

                    setTimeout(function() {{
                        toast.style.opacity = '1';
                    }}, 100);

                    setTimeout(function() {{
                        toast.style.opacity = '0';
                        setTimeout(function() {{
                            toast.remove();
                        }}, 500);
                    }}, 10000);
                </script>
            """, height=0, width=0)

    st.session_state.todo_alert_shown = True

# メニュー設定
page = st.sidebar.radio("🐭🐄🐯🐍 メメニュー 🐏🐗🐒🐩", ["台帳入力🐶", "レシート撮影📷", "リスト管理🐇", "🍋ToDoリスト🍋", "メモ帳📝", "月別集計・リセット🐻", "管理者設定🍖"])

# --- レシート撮影ページ ---
if page == "レシート撮影📷":
    st.header("📸 レシート解析・撮影📷")
    
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0
    if "gemini_items" not in st.session_state:
        st.session_state.gemini_items = None
    if "gemini_place" not in st.session_state:
        st.session_state.gemini_place = ""

    img_file = st.file_uploader(
        "ここをタップしてレシートを撮影 📸", 
        type=["jpg", "jpeg", "png"],
        label_visibility="collapsed",
        key=f"receipt_uploader_{st.session_state.uploader_key}"
    )
    
    if img_file is not None:
        preview_img = Image.open(img_file)
        preview_img = ImageOps.exif_transpose(preview_img)
        
        st.image(preview_img, caption="選択されたレシート", use_container_width=True)
        
        # 解析ボタン
        if st.button("🤖 Geminiでレシートを解析する", use_container_width=True):
            with st.spinner("レシートの情報をAIが読み取っています...⏳"):
                try:
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    prompt = """
                    このレシート画像から以下の情報を抽出し、必ず純粋なJSON形式のみで返してください（マークダウンの ```json と ``` は含めないでください）。
                    {
                      "place": "店名（不明な場合は空文字）",
                      "items": [
                        {
                          "item": "商品名",
                          "amount": 金額（整数）
                        }
                      ]
                    }
                    """
                    response = model.generate_content([prompt, preview_img])
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

    st.write("---")
    
    st.subheader(f"🥎レシート一括削除")
    st.write(f"自分が撮影したレシートのみをすべて削除できるよ蜥")
    
    confirm_all_del = st.checkbox(f"🚙本当に【{current_user}】のレシートを全削除する？栗")
    if st.button(f"🚨 {current_user}のを全削除する", use_container_width=True, disabled=not confirm_all_del):
        with st.spinner(f"{current_user}のデータを一括削除中...⏳"):
            my_receipts = db.collection("receipt_images").where("person", "==", current_user).stream()
            deleted_count = 0
            for doc in my_receipts:
                delete_image(doc.id)
                doc.reference.delete()
                deleted_count += 1
            
            if deleted_count > 0:
                st.success(f"{deleted_count}件のレシートをすべて削除したよ！")
            else:
                st.info("削除するレシートがありませんでした。")
            st.cache_data.clear()
            st.rerun()

    receipt_docs = db.collection("receipt_images").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    receipts = [{"id": doc.id, **doc.to_dict()} for doc in receipt_docs]
    
    if receipts:
        df_receipts = pd.DataFrame(receipts)
        timestamps = [d.get("timestamp") if isinstance(d, dict) else d for d in df_receipts["timestamp"]]
        df_receipts["timestamp"] = pd.to_datetime(timestamps, errors='coerce')
        if df_receipts["timestamp"].dt.tz is None:
            df_receipts["timestamp"] = df_receipts["timestamp"].dt.tz_localize('UTC')
        df_receipts["timestamp"] = df_receipts["timestamp"].dt.tz_convert('Asia/Tokyo')
        df_receipts["日時"] = df_receipts["timestamp"].dt.strftime("%Y/%m/%d %H:%M").fillna("-")
        
        df_daichi = df_receipts[df_receipts["person"] == "大地"]
        df_hinako = df_receipts[df_receipts["person"] == "日向子"]
        
        col_d, col_h = st.columns(2)
        
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
    st.subheader("🚑 やること一覧")
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

# --- メモ帳ページ ---
elif page == "メモ帳📝":
    memo_ref = db.collection("shared_memos").document("shared_memo")
    memo_doc = memo_ref.get()
    
    current_text = ""
    last_updated_by = "なし"
    last_updated_at = "-"

    if memo_doc.exists:
        memo_data = memo_doc.to_dict()
        current_text = memo_data.get("content", "")
        last_updated_by = memo_data.get("updated_by", "不明")
        
        ts = memo_data.get("timestamp")
        if ts:
            dt = pd.to_datetime(ts, errors='coerce')
            if dt is not pd.NaT:
                if dt.tz is None:
                    dt = dt.tz_localize('UTC')
                dt = dt.tz_convert('Asia/Tokyo')
                last_updated_at = dt.strftime("%Y/%m/%d %H:%M")

    st.caption(f"🦆最終更新: **{last_updated_by}** ({last_updated_at})")

    with st.form("simple_memo_form"):
        memo_input = st.text_area(
            "自由記入用ノート",
            value=current_text,
            height=450,
            placeholder="ここに2人で自由にメモを書いてね！\n書き終わったら下の「最新状態に更新する」を押してね✨",
            label_visibility="collapsed"
        )
        
        save_btn = st.form_submit_button("🦒最新状態に更新する🐪", use_container_width=True)

        if save_btn:
            memo_ref.set({
                "content": memo_input,
                "updated_by": current_user,
                "timestamp": firestore.SERVER_TIMESTAMP
            })
            st.success("メモを確定・保存したよ！✨")
            st.cache_data.clear()
            st.rerun()

# --- 月別集計・リセット ---
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
