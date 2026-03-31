/** 숫자 포맷 유틸 */
export const fmt = (n, decimals = 2) =>
  n != null
    ? Number(n).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })
    : '-';

export const fmtUSD = (n) => (n != null ? `$${fmt(n)}` : '-');
export const fmtPct = (n) => (n != null ? `${fmt(n)}%` : '-');
