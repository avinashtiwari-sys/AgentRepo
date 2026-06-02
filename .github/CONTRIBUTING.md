# Contributing to GTMFlow

Thank you for your interest in contributing to GTMFlow!

## Getting Started

1.  **Fork the Repository**: Create your own fork of the project.
2.  **Clone the Fork**: Clone your fork to your local machine.
3.  **Set Up Environment**: Follow the local setup instructions in the root [README.md](../README.md).
4.  **Create a Branch**: Create a new branch for your feature or bug fix.

## Contribution Guidelines

-   **Code Quality**: Ensure your code follows PEP 8 standards.
-   **Testing**: Add tests for new features and ensure all existing tests pass.
-   **Documentation**: Update the README or other documentation if your changes introduce new functionality or configuration options.

## Submitting Changes

1.  **Push to GitHub**: Push your changes to your fork.
2.  **Open a Pull Request**: Submit a PR to the main repository with a clear description of your changes and why they are necessary.

## Development Workflow

-   Use `uvicorn app.main:app --reload` for local development.
-   Test lead processing using `test_webhook.py`.
-   Verify gate logic in `app/gates/`.
