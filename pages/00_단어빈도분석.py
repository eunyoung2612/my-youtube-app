import re
from collections import Counter

import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# =========================================================
# 기본 설정
# =========================================================
st.set_page_config(page_title="유튜브 댓글 분석기", page_icon="💬", layout="wide")

st.title("💬 유튜브 댓글 분석기 (1단계)")
st.write("유튜브 영상 링크를 넣으면, 좋아요가 많은 순서로 댓글을 가져옵니다.")

# 예시로 쓸 링크들을 미리 정의해 둡니다.
EXAMPLE_1_URL = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"
EXAMPLE_2_URL = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"

# st.session_state는 스트림릿 앱이 새로고침(재실행)되어도
# 값을 계속 기억하게 해주는 저장 공간입니다.
# 입력창의 값을 여기에 저장해서, 버튼을 누르면 이 값을 바꿔줍니다.
if "youtube_url" not in st.session_state:
    st.session_state["youtube_url"] = EXAMPLE_1_URL


# =========================================================
# 예시 버튼 두 개 (나란히 배치)
# =========================================================
col1, col2 = st.columns(2)

with col1:
    if st.button("예시 1 · 딥마인드 다큐(영어 댓글)", use_container_width=True):
        st.session_state["youtube_url"] = EXAMPLE_1_URL

with col2:
    if st.button("예시 2 · 2002 월드컵 추억(한국어 댓글)", use_container_width=True):
        st.session_state["youtube_url"] = EXAMPLE_2_URL


# =========================================================
# 유튜브 링크 입력창
# =========================================================
# key="youtube_url"을 지정하면 st.session_state["youtube_url"]과
# 자동으로 연결되어서, 위 버튼으로 바꾼 값이 입력창에 바로 반영됩니다.
youtube_url = st.text_input(
    "유튜브 영상 링크를 붙여넣으세요",
    key="youtube_url",
)


# =========================================================
# 링크에서 영상 ID(video ID) 뽑아내는 함수
# =========================================================
def extract_video_id(url: str) -> str | None:
    """
    유튜브 링크에서 영상 ID만 뽑아내는 함수입니다.
    다음 두 가지 형태를 모두 처리합니다.
      1) https://youtu.be/영상ID?si=...          (짧은 링크)
      2) https://www.youtube.com/watch?v=영상ID&... (일반 링크)
    영상 ID를 못 찾으면 None을 돌려줍니다.
    """
    if not url:
        return None

    url = url.strip()

    # 1) youtu.be/영상ID  형태
    short_match = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if short_match:
        return short_match.group(1)

    # 2) youtube.com/watch?v=영상ID  형태
    long_match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if long_match:
        return long_match.group(1)

    # 3) youtube.com/embed/영상ID  같은 형태도 혹시 몰라 대비
    embed_match = re.search(r"youtube\.com/embed/([A-Za-z0-9_-]{11})", url)
    if embed_match:
        return embed_match.group(1)

    return None


# =========================================================
# YouTube Data API v3로 댓글을 가져오는 함수
# =========================================================
def fetch_comments(video_id: str, api_key: str, max_results: int = 100):
    """
    YouTube Data API v3의 commentThreads 엔드포인트를 호출해서
    댓글을 최대 max_results개 가져옵니다.

    성공하면 (댓글 리스트, None)을 돌려주고,
    실패하면 (None, 에러메시지)를 돌려줍니다.
    댓글 리스트의 각 항목은 {"댓글": 원문, "좋아요": 좋아요수} 형태입니다.
    """
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    comments = []
    page_token = None

    try:
        # 한 번 요청에 최대 100개까지 가져올 수 있으므로,
        # 여기서는 100개를 채울 때까지(또는 더 이상 페이지가 없을 때까지) 반복합니다.
        while len(comments) < max_results:
            params = {
                "part": "snippet",
                "videoId": video_id,
                "order": "relevance",  # 최신순이 아니라 인기(좋아요 많은)순
                "maxResults": min(100, max_results - len(comments)),
                "key": api_key,
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token

            response = requests.get(url, params=params, timeout=10)

            # API가 에러를 돌려준 경우 (잘못된 키, 댓글 사용 중지 등)
            if response.status_code != 200:
                error_reason = ""
                try:
                    error_reason = response.json().get("error", {}).get("message", "")
                except Exception:
                    pass
                return None, f"API 요청이 실패했습니다. (상태 코드: {response.status_code}) {error_reason}"

            data = response.json()
            items = data.get("items", [])

            for item in items:
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "댓글": snippet.get("textOriginal", ""),
                    "좋아요": snippet.get("likeCount", 0),
                })

            # 다음 페이지가 없으면 반복을 멈춥니다.
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return comments, None

    except requests.exceptions.RequestException as e:
        return None, f"네트워크 오류가 발생했습니다: {e}"


# =========================================================
# 댓글에서 자주 나온 단어 상위 20개를 세는 함수
# =========================================================
def count_top_words(comments_list, top_n: int = 20):
    """
    댓글 리스트(딕셔너리의 "댓글" 키)를 모두 합친 뒤,
    단어 단위로 쪼개서 자주 나온 단어 상위 top_n개를 셉니다.

    - 한글, 영어, 숫자를 단어로 인식합니다. (기호/이모지/공백 등은 무시)
    - 영어는 소문자로 통일해서 셉니다. (Apple과 apple을 같은 단어로 취급)
    - 한 글자짜리 단어는 의미가 약한 경우가 많아서 제외합니다.

    결과: [(단어, 등장횟수), ...] 형태의 리스트 (많이 나온 순)
    """
    # 모든 댓글 원문을 하나의 긴 텍스트로 합칩니다.
    full_text = " ".join(c["댓글"] for c in comments_list)

    # 정규식으로 "단어"만 뽑아냅니다.
    # \w는 유니코드 모드에서 한글, 영어, 숫자, 밑줄(_)을 포함합니다.
    raw_words = re.findall(r"\w+", full_text, flags=re.UNICODE)

    # 영어 단어는 소문자로 통일하고, 숫자로만 이루어진 단어와 밑줄(_)만 있는 단어는 제외합니다.
    cleaned_words = []
    for word in raw_words:
        word = word.lower()
        if word.isdigit():
            continue
        if len(word) < 2:  # 한 글자짜리 단어 제외
            continue
        cleaned_words.append(word)

    counter = Counter(cleaned_words)
    return counter.most_common(top_n)


# =========================================================
# 실제 실행 로직
# =========================================================
video_id = extract_video_id(youtube_url)

if not video_id:
    st.warning("⚠️ 유효한 유튜브 링크를 입력해주세요. (예: https://youtu.be/영상ID)")
else:
    # secrets.toml 또는 스트림릿 클라우드의 Secrets 설정에서 API 키를 불러옵니다.
    api_key = st.secrets.get("YOUTUBE_API_KEY", None)

    if not api_key:
        st.error(
            "❗ YouTube API 키가 설정되어 있지 않습니다.\n\n"
            "스트림릿 클라우드의 'Secrets' 설정에 `YOUTUBE_API_KEY`를 추가해주세요."
        )
    else:
        with st.spinner("댓글을 불러오는 중입니다..."):
            comments, error = fetch_comments(video_id, api_key, max_results=100)

        if error:
            # 댓글을 못 가져온 경우: 잘못된 링크, 댓글 사용 중지된 영상 등
            st.error(
                "😥 댓글을 불러오지 못했습니다.\n\n"
                "- 링크가 올바른지 다시 확인해주세요.\n"
                "- 영상 제작자가 댓글 기능을 꺼두었을 수도 있어요.\n"
                "- 비공개 영상이거나 삭제된 영상일 수도 있어요.\n\n"
                f"(자세한 오류: {error})"
            )
        elif not comments:
            st.info("이 영상에는 댓글이 없는 것 같아요.")
        else:
            # 좋아요 많은 순으로 정렬 (API도 relevance순이지만, 한 번 더 확실하게 정렬)
            comments_sorted = sorted(comments, key=lambda c: c["좋아요"], reverse=True)

            # 지표 카드로 댓글 개수 크게 보여주기
            st.metric("가져온 댓글 개수", f"{len(comments_sorted)}개")

            # 댓글 목록을 표로 보여주기
            df = pd.DataFrame(comments_sorted)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # =================================================
            # 자주 나온 단어 상위 20개 - 가로 막대그래프
            # =================================================
            st.subheader("📊 자주 나온 단어 상위 20개")

            top_words = count_top_words(comments_sorted, top_n=20)

            if not top_words:
                st.info("단어를 분석할 만한 댓글 내용이 부족해요.")
            else:
                # top_words는 [("단어", 횟수), ...] 형태이며 많이 나온 순으로 정렬되어 있습니다.
                words = [w for w, _ in top_words]
                counts = [c for _, c in top_words]

                # plotly 가로 막대그래프는 리스트의 "아래쪽"부터 그려지기 때문에,
                # 가장 많이 나온 단어가 맨 위에 오게 하려면 순서를 뒤집어서 넣어줘야 합니다.
                words_reversed = words[::-1]
                counts_reversed = counts[::-1]

                fig = go.Figure(
                    go.Bar(
                        x=counts_reversed,
                        y=words_reversed,
                        orientation="h",
                        marker=dict(color="#FF4B4B"),
                        text=counts_reversed,
                        textposition="outside",
                    )
                )
                fig.update_layout(
                    xaxis_title="등장 횟수",
                    yaxis_title="단어",
                    height=600,
                    margin=dict(l=10, r=10, t=30, b=10),
                )

                st.plotly_chart(fig, use_container_width=True)
