# Metrics

Quality metrics for evaluating workflow performance.

## Common Metrics

- **Precision**: True positives / (True positives + False positives)
- **Recall**: True positives / (True positives + False negatives)
- **F1 Score**: Harmonic mean of precision and recall
- **Accuracy**: Correct predictions / Total predictions
- **ROC-AUC**: Area under ROC curve
- **PR-AUC**: Area under precision-recall curve

## Example

```python
from atlas-chat_validation_tools.metrics import calculate_metrics

metrics = calculate_metrics(
    predictions=workflow_output,
    ground_truth=gold_standard
)

print(f"Precision: {metrics.precision:.3f}")
print(f"Recall: {metrics.recall:.3f}")
print(f"F1: {metrics.f1:.3f}")
```
