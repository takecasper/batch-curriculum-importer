# Security Policy

## Supported Versions

Only the latest release gets security fixes. Fixes ship in a new release, not as patches to older ones.

| Version | Supported          |
| ------- | ------------------ |
| 0.3.x   | :white_check_mark: |
| < 0.3   | :x:                |

## Scope

One45 Schedule Wrangler runs on your own Mac and reads and writes workbooks on local disk. It does not send workbook data anywhere. Its only network access is in the app launcher, which checks python.org for a Python installer and opens the download only if it carries the Python Software Foundation's Apple Developer ID signature.

In scope:

- The Wrangler, the window, the app launcher and the build scripts in this repository
- The Python download and signature check
- Workbook handling, such as a crafted `.xlsx` that makes the Wrangler write outside its output folder or run code

Out of scope:

- Vulnerabilities in One45 itself. This tool only prepares files for its importer.
- Vulnerabilities in third-party dependencies (such as `openpyxl`) that this tool does not make worse. Please report those upstream.

## Reporting a Vulnerability

Please do not open a public issue. Report it privately through GitHub instead: go to the repository's **Security** tab and choose **Report a vulnerability**.

Include the version, your macOS version, steps to reproduce and what an attacker could do. Do not attach real Partner Workbooks or any personal data. A small made-up workbook that shows the problem is best.

What to expect:

- **Acknowledgement** within 5 business days.
- **Updates** at least every 14 days until the report is resolved.
- **Accepted:** we fix it in a new release, publish a GitHub security advisory and credit you unless you would rather stay anonymous.
- **Declined:** we explain why, for example because it is out of scope or not reproducible.
