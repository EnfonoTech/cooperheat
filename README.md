### cooperheat

Frappe app for monthly payroll processing: Excel-driven import, per-employee
compensation master with date-versioned records, automatic proration and
overtime/GOSI calculations, two pay-sheet reports, and ERPNext Salary Slip
integration.

### Documentation

- [User Guide](docs/USER_GUIDE.md) — for HR / payroll users running the
  monthly cycle (setup, import, review, reports, slips).
- [Developer Documentation](docs/DEVELOPER.md) — architecture, data model,
  calculation flows, extension points.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app cooperheat
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/cooperheat
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
