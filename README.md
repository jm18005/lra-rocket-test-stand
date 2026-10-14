- Python tools for automating `.ded` file generation for Stabileo. Create your own branches and push to the repo when you make edits so everyone can work off of it.

- `ded_parser.py` and `data/*` are the files you want here, feel free to add to the CSV using `ai_example_code/material_scraper.py`

- Work in this repo will include creating a file that loops through all possible combinations of materials/sections per member, as well as varies the height of the transverse load applied, runs the file automatically through a local clone of Stabileo (https://github.com/lambdaclass/stabileo), and parses the results and returns if the design works or not, and is better than any previously working designs in terms of cost/weight.

- Work may also be analysis and pre-test scripts like an OpenRocket file parser, automatic force location and magnitude generator, etc.

- `ai_example_code/*` is AI generated code that I have not verified, I can only vouch for `ded_parser.py`. The intent is to be able to convert Stabileo files to OpenSees files (a trusted research grade FEA solver that can be automated in Python) to have 2 independant solvers run and verify each other.
