# Dashboard screenshots

The images in this folder are **design mockups** of the 6 Power BI report pages. They are rendered in Python (`python/render_dashboard_mockups.py`) from the project's MySQL data, and every number equals the DAX expected value. Power BI Desktop is Windows-only and the project was built on Linux, so these are **not Power BI screenshots**. Every file name ends in `_mockup`, and every image says so in its footer.

| Page | Image |
|---|---|
| 1 Executive Overview | [page1_executive_overview_mockup.png](page1_executive_overview_mockup.png) |
| 2 Regional Performance | [page2_regional_performance_mockup.png](page2_regional_performance_mockup.png) |
| 3 Investment & ROI | [page3_investment_roi_mockup.png](page3_investment_roi_mockup.png) |
| 4 Energy Performance | [page4_energy_performance_mockup.png](page4_energy_performance_mockup.png) |
| 5 Sustainability | [page5_sustainability_mockup.png](page5_sustainability_mockup.png) |
| 6 Investment Recommendation | [page6_investment_recommendation_mockup.png](page6_investment_recommendation_mockup.png) |

**After building the `.pbix`** on Windows ([build guide](../powerbi/03_dashboard_design.md)): export each page as `page1_executive_overview.png` … `page6_investment_recommendation.png` (without `_mockup`), add `model_view.png`, delete the mockup copies, and point the README at the real images.
