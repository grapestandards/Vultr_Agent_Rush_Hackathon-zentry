/** Money arrives as integer satang; format only at the UI edge. */
export const thb = (satang: number) =>
	`฿${(satang / 100).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
