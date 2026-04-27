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
  const AUXILIARY_BUCKET_ORDER = [
    "financial",
    "shareholder",
    "technical",
    "timestamped",
    "membership",
    "description",
    "alias",
  ];

  function formatAuxiliaryBucketLabel(bucket) {
    const normalizedBucket = typeof bucket === "string" ? bucket.trim() : "";
    return AUXILIARY_BUCKET_LABELS[normalizedBucket] || AUXILIARY_BUCKET_LABELS.unknown;
  }

  function sortAuxiliaryBuckets(entries) {
    if (!Array.isArray(entries)) {
      return [];
    }

    return entries
      .map((entry, index) => [entry, index])
      .sort(([leftEntry, leftIndex], [rightEntry, rightIndex]) => {
        const leftBucket = typeof leftEntry[0] === "string" ? leftEntry[0].trim() : "";
        const rightBucket = typeof rightEntry[0] === "string" ? rightEntry[0].trim() : "";
        const leftOrder = AUXILIARY_BUCKET_ORDER.indexOf(leftBucket);
        const rightOrder = AUXILIARY_BUCKET_ORDER.indexOf(rightBucket);
        const normalizedLeftOrder = leftOrder === -1 ? AUXILIARY_BUCKET_ORDER.length : leftOrder;
        const normalizedRightOrder = rightOrder === -1 ? AUXILIARY_BUCKET_ORDER.length : rightOrder;

        if (normalizedLeftOrder !== normalizedRightOrder) {
          return normalizedLeftOrder - normalizedRightOrder;
        }
        return leftIndex - rightIndex;
      })
      .map(([entry]) => entry);
  }

  const api = {
    AUXILIARY_BUCKET_ORDER,
    AUXILIARY_BUCKET_LABELS,
    formatAuxiliaryBucketLabel,
    sortAuxiliaryBuckets,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  globalScope.ProfileUtils = api;
})(typeof window !== "undefined" ? window : globalThis);
