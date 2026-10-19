// 고르는 방식 3가지의 규칙. 디자인(A/B 페이지)은 이 결과만 그린다. data.js 다음에 불러온다.

// 1. 추천 Top 3: 기준선 F4 결과(top3)와 남은 날 묶음
function top3() { return EXHIBITIONS.filter((x) => x.top3).sort((a, b) => a.top3 - b.top3); }
const GROUPS = [
  { en: "TODAY", ko: "오늘 닫음", f: (x) => x.days === 0 },
  { en: "THIS WEEK", ko: "이번 주에 닫음", f: (x) => x.days > 0 && x.days <= 7 },
  { en: "LATER", ko: "더 오래 함", f: (x) => x.days > 7 },
];
function byDays(xs) { return xs.slice().sort((a, b) => a.days - b.days || a.title.localeCompare(b.title)); }

// 2. 시간 동선: 오늘 닫는 전시가 많은 동네부터 시간 예산 안에서 채운다 (동네, 관람 시간은 시안용 가정)
const MOVE_IN_AREA = 10, MOVE_BETWEEN = 40;
const BUDGETS = [{ min: 120, label: "2시간" }, { min: 240, label: "반나절" }, { min: 480, label: "하루" }];
function planRoute(budget) {
  const urgency = (x) => (x.days === 0 ? 3 : x.days <= 7 ? 2 : 1);
  const areas = {};
  EXHIBITIONS.filter((x) => x.area !== "위치 미확인").forEach((x) => (areas[x.area] ||= []).push(x));
  const ranked = Object.entries(areas)
    .map(([name, xs]) => ({ name, xs: xs.slice().sort((a, b) => a.days - b.days || a.gallery.localeCompare(b.gallery)), u: xs.reduce((s, x) => s + urgency(x), 0) }))
    .sort((a, b) => b.u - a.u);
  const legs = [];
  let used = 0;
  for (const [i, area] of ranked.entries()) {
    if (i > 0) { if (used + MOVE_BETWEEN > budget) break; used += MOVE_BETWEEN; }
    const leg = { name: area.name, move: i > 0, xs: [] };
    for (const x of area.xs) {
      const cost = x.minutes + MOVE_IN_AREA;
      if (used + cost > budget) continue;
      used += cost; leg.xs.push(x);
    }
    if (leg.xs.length) legs.push(leg);
  }
  const picked = legs.flatMap((l) => l.xs);
  const ids = new Set(picked.map((x) => x.id));
  return { legs, picked, hours: Math.round(used / 30) / 2, closing: picked.filter((x) => x.days === 0).length, rest: byDays(EXHIBITIONS.filter((x) => !ids.has(x.id))) };
}

// 3. 질문형: 남은 날로 나누고, 정보 확인된 것만 거를 수 있다
const QUESTIONS = [
  { k: "today", label: "오늘 아니면 못 봄", rule: "오늘 닫는 전시", f: (x) => x.days === 0 },
  { k: "week", label: "이번 주 안에", rule: "1~7일 뒤 닫는 전시", f: (x) => x.days > 0 && x.days <= 7 },
  { k: "slow", label: "급하지 않음", rule: "8일 넘게 남은 전시", f: (x) => x.days > 7 },
  { k: "all", label: "전부", rule: "진행 중인 전시 전부, 닫는 날 순", f: () => true },
];
function answer(k, sureOnly) {
  const pool = byDays(EXHIBITIONS.filter((x) => !sureOnly || !badges(x).length));
  return { counts: Object.fromEntries(QUESTIONS.map((q) => [q.k, pool.filter(q.f).length])), shown: pool.filter(QUESTIONS.find((q) => q.k === k).f), rule: QUESTIONS.find((q) => q.k === k).rule };
}

// 버튼 묶음: 누른 것만 aria-pressed=true로 두고 콜백을 부른다
function bindSeg(root, onPick) {
  root.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    root.querySelectorAll("button").forEach((o) => o.setAttribute("aria-pressed", o === b));
    onPick(b.dataset.v);
  }));
}
function md(s) { return +s.slice(5, 7) + "월 " + +s.slice(8) + "일"; }
