export const INTENT_GROUPS = [
  {
    id: "G1",
    label: "Category & local discovery",
    desc: "Unbranded provider/category discovery queries",
  },
  {
    id: "G2",
    label: "Direct brand",
    desc: "Client-named branded decision queries",
  },
  {
    id: "G3",
    label: "Competitors & alternatives",
    desc: "Switching, alternatives, and competitive comparison queries",
  },
  {
    id: "G4",
    label: "Transactional & bottom-funnel",
    desc: "Cost, quote, booking, buying, and urgency queries",
  },
  {
    id: "G5",
    label: "Trust, reviews & risk",
    desc: "Review, reputation, safety, and pre-purchase risk queries",
  },
  {
    id: "G6",
    label: "Fit: persona, occasion, constraint",
    desc: "Best-fit queries for specific audiences, occasions, and constraints",
  },
  {
    id: "G7",
    label: "Head-to-head choice",
    desc: "Shortlist, pick-one, and final decision queries",
  },
] as const;

export type IntentGroupId = (typeof INTENT_GROUPS)[number]["id"];
