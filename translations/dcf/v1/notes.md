# Discounted cash flow v1

I translated the DCF sheet formula for formula and kept the workbook's order of operations so the results match.

How the code maps to the sheet:
- B3 levered beta = bu*(1+(1-t)*D/Cap/(1-D/Cap)). B4 cost of equity = rf + levered beta*ERP + size premium. B5 after-tax cost of debt = kd*(1-t). B6 WACC = (1-D/Cap)*cost of equity + D/Cap*after-tax cost of debt.
- Rows 9 to 18 are the projection. Revenue compounds from LTM by g_y1 to g_y5. EBITDA, D&A and capex are each revenue times the relevant percentage. EBIT = EBITDA - D&A. Taxes = EBIT*t. Change in NWC = increase in revenue * nwc_pct_incr_rev. FCF = EBIT - taxes + D&A - capex - change in NWC. The discount factor is 1/(1+WACC)^n, end of year, and PV = FCF*factor.
- B20 sums the PVs. B21 terminal value = year-5 FCF*(1+g)/(WACC-g). B22 discounts the terminal value with the year-5 factor. B23 = B20 + B22 gives mid.
- B24 (low) and B25 (high) are reproduced as written. They recompute the PVs and the Gordon terminal value at WACC ± step and g ∓ step, with WACC and growth moved in the same step.

Points a reviewer should know (all reproduced as is, not changed):
1. Low and high are the two extreme corners only (WACC up and g down together, and the reverse). They are not a grid and not a probability range, so the band is wide and sits off-centre around mid.
2. The steps come from Inputs!C31 and C32. These are not engine input keys, so I hard-coded them as defaults (0.01 and 0.005) and let `values` override them.
3. Taxes have no floor at zero. A negative EBIT would produce a tax credit. The code reproduces this and adds a warning.
4. D&A is driven by revenue on its own, not tied to the EBITDA margin. With D&A at 4.5% of revenue and capex at 5%, terminal FCF assumes capex runs only slightly above D&A for ever. This is a judgement for the first line to defend, not a formula error.
5. The terminal value has no guard for WACC ≤ g. If they are equal, Excel shows #DIV/0!; the code raises ValueError. If WACC is below g, the workbook gives a meaningless negative value; the code reproduces it and adds a warning. The same applies to the high case, where the gap narrows by both steps.
6. Three inputs are not used on this sheet: ebitda_ltm, private_discount and the method weights. The private-company discount is not applied in the DCF. If it is applied anywhere, it would be on the Summary sheet, which is out of scope here.
7. Claims are accepted and ignored, because this is an enterprise-value method.

## Assumptions

- The workbook constants wacc_step = 0.01 (Inputs!C31) and growth_step = 0.005 (Inputs!C32) are the defaults because they are not engine input keys.
- When a formula would divide by zero (#DIV/0! in Excel), the code raises ValueError instead of returning a number.
- Python's ** operator and IEEE floating point may differ from Excel's ^ in the last few bits. After rounding with r2, the values should match B23, B24 and B25.
- The year rows in details are rounded to 2 decimals. WACC, the rates and the discount factors are left unrounded.
