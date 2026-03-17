# Visualizations

Analysis visualizations for workflow results.

## Available Visualizations

- **Heatmaps**: Result matrices, correlation analysis
- **ROC Curves**: Classification performance
- **Precision-Recall Curves**: Threshold analysis
- **Confusion Matrices**: Classification breakdown
- **Time Series**: Performance over time
- **Comparison Charts**: Side-by-side analysis

## Example

```python
from atlas-chat_validation_tools.visualizations import plot_roc_curve

fig = plot_roc_curve(
    y_true=ground_truth,
    y_scores=predictions,
    title="Workflow Performance"
)

fig.savefig("outputs/roc_curve.png")
```
