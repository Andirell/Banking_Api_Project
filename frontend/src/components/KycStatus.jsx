// Works out what the customer should see for their current KYC state.
export function getKycSummary(user) {
  if (user.kyc_status === "verified") {
    return {
      tone: "good",
      label: "Verified",
      text: "Your identity is verified. Larger transfers and loans are available.",
    };
  }
  if (user.kyc_status === "rejected") {
    return {
      tone: "bad",
      label: "Needs attention",
      text: user.kyc_rejection_reason || "Your documents were not accepted. Please upload them again.",
    };
  }
  if (user.kyc_documents_submitted) {
    return {
      tone: "waiting",
      label: "In review",
      text: "Staff are reviewing your documents. Larger transfers and loans unlock once approved.",
    };
  }
  return {
    tone: "waiting",
    label: "Not started",
    text: "Upload your documents to unlock larger transfers and loans.",
  };
}

export function KycBadge({ user }) {
  const summary = getKycSummary(user);
  return <span className={`badge badge-${summary.tone}`}>{summary.label}</span>;
}
