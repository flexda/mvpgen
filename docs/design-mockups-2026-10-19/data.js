// 기준선 앱(run 39119897521)의 GET /api/today?date=2026-10-18 결과를 옮긴 것.
// days: 기준일부터 종료일까지 남은 날. score: 기준선 F4 점수. top3: 기준선 '오늘의 추천'.
// area, minutes: 시안용 가정이다. CSV와 spec에 없는 값이고 확인하지 않았다.
const BASE_DATE = "2026-10-18";
const BASE_LABEL = "10월 18일 일요일";
const GALLERY_REF_DATE = "2026-10-06";

const EXHIBITIONS = [
  { id: 1, title: "Changing Unchanging 변하는 변하지 않는", artists: "Park Seo-Bo", gallery: "국제갤러리", branch: "K1·K3·한옥", start: "2026-08-24", end: "2026-10-18", days: 0, review: "", score: 4, top3: 1, area: "삼청·북촌", minutes: 50 },
  { id: 3, title: "Moon Mind 달 마음", artists: "Christine Sun Kim", gallery: "갤러리현대", branch: "", start: "2026-08-26", end: "2026-10-18", days: 0, review: "", score: 4, top3: 2, area: "삼청·북촌", minutes: 30 },
  { id: 2, title: "Pictos and Pitwall 핏월과 픽토", artists: "Seeun Kim", gallery: "국제갤러리", branch: "K2", start: "2026-08-24", end: "2026-10-18", days: 0, review: "", score: 4, top3: 0, area: "삼청·북촌", minutes: 20 },
  { id: 4, title: "Towards: There Was Light", artists: "Kim Bohie", gallery: "갤러리현대", branch: "", start: "2026-08-26", end: "2026-10-18", days: 0, review: "", score: 4, top3: 0, area: "삼청·북촌", minutes: 30 },
  { id: 13, title: "Míope 편린", artists: "Marina Rheingantz", gallery: "화이트큐브 서울", branch: "서울", start: "2026-09-01", end: "2026-10-24", days: 6, review: "", score: 4, top3: 3, area: "도산·청담", minutes: 30 },
  { id: 12, title: "The Nearest Faraway Place", artists: "Friedrich Kunath", gallery: "페이스갤러리 서울", branch: "Seoul", start: "2026-09-01", end: "2026-10-24", days: 6, review: "", score: 4, top3: 0, area: "한남", minutes: 30 },
  { id: 14, title: "내일의 문턱에서", artists: "Mr.", gallery: "페로탕 서울", branch: "서울(도산파크)", start: "2026-09-01", end: "2026-10-24", days: 6, review: "갤러리 페이지 미반영(캐시) → 언론 교차확인", score: 3, top3: 0, area: "도산·청담", minutes: 30 },
  { id: 8, title: "잠자는 남자", artists: "김인배", gallery: "아라리오갤러리", branch: "서울", start: "", end: "2026-10-24", days: 6, review: "시작일 미확인 / 갤러리 페이지는 지난 전시 표시", score: 3, top3: 0, area: "삼청·북촌", minutes: 30 },
  { id: 9, title: "Georg Baselitz 전시 (전시명 미표기)", artists: "Georg Baselitz", gallery: "타데우스 로팍 서울", branch: "Seoul Fort Hill", start: "2026-09-01", end: "2026-11-14", days: 27, review: "전시명 미표기", score: 0, top3: 0, area: "한남", minutes: 30 },
  { id: 5, title: "Meditation: Myth and Memory", artists: "John Pai", gallery: "갤러리현대", branch: "", start: "2026-09-10", end: "2026-11-28", days: 41, review: "", score: 1, top3: 0, area: "삼청·북촌", minutes: 30 },
  { id: 7, title: "Yun Hyong-keun House", artists: "Yun Hyong-keun", gallery: "PKM갤러리", branch: "Yun Hyong-keun House", start: "2026-02-04", end: "2026-12-05", days: 48, review: "", score: 1, top3: 0, area: "위치 미확인", minutes: 30 },
];

function dLabel(days) { return days === 0 ? "오늘 종료" : "D-" + days; }
function period(x) {
  const f = (s) => s.slice(5).replace("-", ".");
  return (x.start ? f(x.start) : "시작일 미확인") + " – " + f(x.end);
}
function place(x) { return x.branch && x.branch !== "서울" && x.branch !== "Seoul" ? x.gallery + " · " + x.branch : x.gallery; }
function badges(x) {
  const out = [];
  if (!x.start) out.push("시작일 미확인");
  if (x.review) out.push("정보 확인 필요");
  return out;
}
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
