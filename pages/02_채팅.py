import re
import requests
import streamlit as st
from openai import OpenAI

# ------------------------------------------------------------
# 기본 설정
# ------------------------------------------------------------
st.set_page_config(page_title="유튜브 댓글 AI 요약", page_icon="💬", layout="centered")

기본_링크 = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"
예시2_링크 = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"

# 세션에 입력창 값을 저장해둘 공간을 미리 만들어줌
if "url_input" not in st.session_state:
    st.session_state.url_input = 기본_링크

# 댓글 목록을 세션에 저장해둘 공간
if "comments" not in st.session_state:
    st.session_state.comments = None

st.title("💬 유튜브 댓글 AI 요약")
st.caption("영상 링크를 넣으면 댓글을 가져오고, AI가 세 줄로 요약해줍니다.")

# ------------------------------------------------------------
# 예시 버튼 두 개 (나란히 배치)
# ------------------------------------------------------------
col1, col2 = st.columns(2)
with col1:
    if st.button("예시 1 · 딥마인드 다큐(영어 댓글)", use_container_width=True):
        st.session_state.url_input = 기본_링크
with col2:
    if st.button("예시 2 · 2002 월드컵 추억(한국어 댓글)", use_container_width=True):
        st.session_state.url_input = 예시2_링크

# ------------------------------------------------------------
# 링크 입력창
# ------------------------------------------------------------
영상_링크 = st.text_input("유튜브 영상 링크를 붙여넣으세요", key="url_input")


def 영상아이디_추출(url: str):
    """
    유튜브 링크에서 영상 ID만 뽑아내는 함수.
    - youtu.be/영상ID 형태
    - youtube.com/watch?v=영상ID 형태
    둘 다 처리하고, si= 같은 뒤에 붙는 값은 무시함.
    """
    if not url:
        return None

    # 패턴1: youtu.be/영상ID
    짧은주소_패턴 = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if 짧은주소_패턴:
        return 짧은주소_패턴.group(1)

    # 패턴2: youtube.com/watch?v=영상ID
    긴주소_패턴 = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if 긴주소_패턴:
        return 긴주소_패턴.group(1)

    return None


def 댓글_가져오기(영상아이디: str):
    """
    YouTube Data API v3의 commentThreads 창구를 호출해서
    좋아요 많은 순(order=relevance)으로 댓글을 최대 100개까지 가져오는 함수.
    성공하면 [{"text": 댓글내용, "likes": 좋아요수}, ...] 리스트를 돌려주고
    실패하면 None을 돌려줌.
    """
    try:
        api_key = st.secrets["YOUTUBE_API_KEY"]
    except Exception:
        st.error("⚠️ 유튜브 API 키(YOUTUBE_API_KEY)가 secrets에 설정되어 있지 않아요.")
        return None

    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": 영상아이디,
        "order": "relevance",   # 최신순이 아니라 좋아요(관련도) 많은 순
        "maxResults": 100,
        "textFormat": "plainText",
        "key": api_key,
    }

    try:
        응답 = requests.get(url, params=params, timeout=10)
        응답.raise_for_status()
        데이터 = 응답.json()
    except Exception:
        return None

    댓글목록 = []
    for item in 데이터.get("items", []):
        try:
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            댓글목록.append({
                "text": snippet.get("textOriginal", ""),
                "likes": snippet.get("likeCount", 0),
            })
        except (KeyError, TypeError):
            continue

    if not 댓글목록:
        return None

    # 좋아요 많은 순으로 한 번 더 정렬 (혹시 모를 순서 보정용)
    댓글목록.sort(key=lambda x: x["likes"], reverse=True)
    return 댓글목록


def AI_세줄요약(댓글목록):
    """
    Solar API(solar-open2 모델)를 이용해 댓글 전체를 한국어 세 줄로 요약하는 함수.
    마지막 줄에는 긍정/부정 비율 추정치를 붙임.
    성공하면 요약 문자열, 실패하면 None을 돌려줌.
    """
    try:
        api_key = st.secrets["SOLAR_API_KEY"]
    except Exception:
        st.error("⚠️ Solar API 키(SOLAR_API_KEY)가 secrets에 설정되어 있지 않아요.")
        return None

    # 댓글들을 한 덩어리 텍스트로 합침
    댓글텍스트 = "\n".join(f"- {c['text']} (좋아요 {c['likes']}개)" for c in 댓글목록)

    프롬프트 = (
        "다음은 어떤 유튜브 영상에 달린 댓글들이야. "
        "이 댓글들의 전체 반응을 한국어로 정확히 세 줄로 요약해줘. "
        "그리고 마지막 줄에는 댓글 반응의 긍정/부정 비율을 대략적인 백분율로 추정해서 함께 적어줘.\n\n"
        f"{댓글텍스트}"
    )

    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.upstage.ai/v1",
        )
        응답 = client.chat.completions.create(
            model="solar-open2",
            messages=[{"role": "user", "content": 프롬프트}],
            reasoning_effort="none",  # 추론(생각) 기능 끄기
        )
        return 응답.choices[0].message.content
    except Exception:
        return None


# ------------------------------------------------------------
# 댓글 가져오기 버튼
# ------------------------------------------------------------
if st.button("📥 댓글 가져오기", type="primary", use_container_width=True):
    영상아이디 = 영상아이디_추출(영상_링크)

    if not 영상아이디:
        st.error("⚠️ 링크에서 영상 ID를 찾을 수 없어요. 유튜브 링크가 맞는지 확인해주세요.")
    else:
        with st.spinner("댓글을 가져오는 중이에요..."):
            댓글목록 = 댓글_가져오기(영상아이디)

        if 댓글목록 is None:
            st.error(
                "⚠️ 댓글을 가져오지 못했어요. "
                "영상에 댓글이 없거나, 댓글이 막혀있거나, API 키/할당량 문제일 수 있어요."
            )
            st.session_state.comments = None
        else:
            st.session_state.comments = 댓글목록
            st.success(f"댓글 {len(댓글목록)}개를 가져왔어요!")

# ------------------------------------------------------------
# 가져온 댓글 보여주기
# ------------------------------------------------------------
if st.session_state.comments:
    댓글목록 = st.session_state.comments

    st.metric("가져온 댓글 개수", f"{len(댓글목록)}개")

    표데이터 = [{"댓글": c["text"], "좋아요": c["likes"]} for c in 댓글목록]
    st.dataframe(표데이터, use_container_width=True)

    st.divider()

    # ------------------------------------------------------------
    # AI 세 줄 요약 버튼
    # ------------------------------------------------------------
    if st.button("✨ AI 세 줄 요약", use_container_width=True):
        with st.spinner("AI가 댓글을 읽고 요약하는 중이에요..."):
            요약결과 = AI_세줄요약(댓글목록)

        if 요약결과 is None:
            st.error(
                "⚠️ 요약에 실패했어요. "
                "AI 키(SOLAR_API_KEY)가 올바른지, 네트워크 상태가 괜찮은지 확인해주세요."
            )
        else:
            st.subheader("📝 AI 세 줄 요약")
            st.write(요약결과)
