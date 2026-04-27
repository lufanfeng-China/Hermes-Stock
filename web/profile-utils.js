(function initProfileUtilsModule(globalScope) {
  const AUXILIARY_BUCKET_LABELS = {
    membership: "风格/成分",
    technical: "技术标签",
    financial: "财务标签",
    shareholder: "股东/持股",
    timestamped: "时点标签",
    description: "业务描述",
    alias: "历史简称",
    unknown: "其他标签",
  };

  function formatAuxiliaryBucketLabel(bucket) {
    const normalizedBucket = typeof bucket === "string" ? bucket.trim() : "";
    return AUXILIARY_BUCKET_LABELS[normalizedBucket] || AUXILIARY_BUCKET_LABELS.unknown;
  }

  const api = {
    AUXILIARY_BUCKET_LABELS,
    formatAuxiliaryBucketLabel,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  globalScope.ProfileUtils = api;
})(typeof window !== "undefined" ? window : globalThis);
