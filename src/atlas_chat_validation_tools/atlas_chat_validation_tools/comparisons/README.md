# Comparisons

Tools for comparing workflow runs and outputs.

## Use Cases

- Compare results from different workflow versions
- Diff analysis between parameter configurations
- Side-by-side output comparison
- Regression testing (current vs baseline)

## Example

```python
from atlas-chat_validation_tools.comparisons import compare_runs

result = compare_runs(
    run1_output="outputs/run1/final.json",
    run2_output="outputs/run2/final.json"
)

print(result.differences)
print(result.similarity_score)
```
