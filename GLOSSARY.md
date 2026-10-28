# One45 Schedule Wrangler

Partners usually send their whole curriculum at once, as many per-Course schedule files spread across several Portfolios. One45 Schedule Wrangler regroups those files into a Batch Import with one Portfolio Tab per Portfolio, so each Portfolio takes one import instead of one per file.

## Language

### Tool and output

**Partner**:
A school that sends its schedules to be imported into One45.
_Avoid_: client, customer, school

**Batch**:
The set of Partner Workbooks that one Partner sends for one term, processed together, such as every Course upload for Spring 2026.
_Avoid_: run, job, upload

**Check Run**:
Processing a Batch of one Partner Workbook to validate and normalize it. The output is a Portfolio Tab for each Portfolio in the file, or one Course Tab when the file has no Portfolio.
_Avoid_: single-file mode

**Combine Run**:
Processing a Batch of two or more Partner Workbooks into Portfolio Tabs.
_Avoid_: merge, multi-file mode

**One45 Schedule Wrangler**:
The tool that turns a Batch into a Batch Import.
_Avoid_: One45 Wrangler, batchlore, Schedule Master Workbook

**Batch Import**:
What One45 Schedule Wrangler produces: one workbook of Portfolio Tabs (or a single Course Tab) plus a Change Log Tab, or, when asked for a file per Portfolio, a folder with one such workbook per Portfolio.
_Avoid_: Master Schedule, master workbook, output file

**Flagged Cell**:
A cell in the Batch Import, marked red, that needs a person's judgment before import. Today that means only an End Time that is not after its Start Time, where the correct time has to be inferred or confirmed with the Partner.
_Avoid_: error, warning

**Portfolio Tab**:
A tab in the Batch Import holding every row for one Portfolio. Its name is the Portfolio, and it has no portfolio column, because One45 rejects an import file that contains one.
_Avoid_: portfolio sheet, course tab

**Course Tab**:
A tab in the Batch Import named after a Course, used only when the Batch holds a single Course and no Portfolio. The importer picks the Portfolio at import time. A Batch of several Courses with no Portfolio never gets Course Tabs: someone must say which Portfolio they belong to.
_Avoid_: course sheet

**File Tab**:
A tab in the Batch Import named after a Partner Workbook, holding that workbook's rows that have no Portfolio. Made only when someone chooses "Give each its own tab" (`--unassigned-file-tabs`). The importer picks its Portfolio at import time.
_Avoid_: unassigned tab, review tab

**Change Log Tab**:
The "Change Log" tab, always last in each Batch Import workbook, listing every change One45 Schedule Wrangler made between the Partner Workbooks and that workbook: skipped sheets, renamed, dropped or added columns, fixed or unreadable times and dates, flagged rows, Portfolios filled in, and workbooks given a File Tab. It is never imported.
_Avoid_: audit log, diff

### Input

**Partner Workbook**:
One `.xlsx` file a Partner sends, usually covering one Course.
_Avoid_: course file, source file

**Schedule Sheet**:
The tab in a Partner Workbook that holds Sections to import. Partners call it the "Schedule Upload".
_Avoid_: schedule tab

**Mapping Sheet**:
The tab in a Partner Workbook that maps Sessions to objectives and competencies. Partners call it the "Mapping Upload". One45 Schedule Wrangler does not process it.
_Avoid_: Curriculum Sheet, objectives tab

### Curriculum (One45)

**Portfolio**:
The One45 container that a schedule is imported into. It is usually scoped to a term and a cohort, such as "Summer 2026, MED 4". The importer selects it at import time, and every Course on a Portfolio Tab is imported into it.

**Course**:
A unit of curriculum within a Portfolio, such as "Intro to Biology".

**Subcourse**:
An optional subdivision of a Course that some partners use for weeks or blocks, such as "Intro to Biology > Week 1".
_Avoid_: block, module

**Session**:
An individual educational activity within a Course, such as a lecture, lab, or seminar.
_Avoid_: event

**Section**:
A specific scheduled instance of a Session, usually set apart by date, time, or student group.
_Avoid_: occurrence, class
