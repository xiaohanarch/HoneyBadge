# M1 Finding: hermes-agent availability

- **PyPI**: YES — `hermes-agent` version 0.17.0
- **Author**: Nous Research
- **License**: MIT
- **Requires Python**: >=3.11, <3.14
- **Worker container Python**: 3.12.3 (satisfies constraint)
- **Summary**: "The self-improving AI agent — creates skills from experience, improves them during use, and runs anywhere"
- **Installation method**: `pip3 install --break-system-packages hermes-agent`
- **Version**: 0.17.0

## Q2-Q5 status (deferred to M2-M4)

- **Q2** (config.yaml schema): Will be verified during image build (Task 1) by running `hermes-agent --help` and checking docs at hermes-agent.nousresearch.com
- **Q3** (health check endpoint): Will be verified during M2 by checking `hermes-agent --help`
- **Q4** (Matrix E2EE): Will be verified during M4 integration test
- **Q5** (exec tool for mcporter): MOOT for Approach B — Python modules call mcporter via `subprocess.run()`, not via hermes `exec` tool

## Conclusion: M1 GATE PASSED. Proceed to implementation.
