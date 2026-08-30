# paperkit -- build the paper in any venue mode.
#
#   make            # same as `make arxiv'
#   make arxiv1col  # one-column preprint, acmsmall proportions on US Letter
#   make OPTS=acmtrim arxiv1col   # acmsmall's own 6.75x10in page at 10pt
#   make neurips    # NeurIPS submission (anonymous)
#   make icml       # ICML submission (anonymous)
#   make plain      # plain article, no venue style
#   make example    # examples/arxiv1col-demo.pdf, the acmsmall layout in use
#   make FINAL=1 neurips     # camera-ready / de-anonymized
#   make clean      # remove build artifacts
#
# Each target writes main.pdf and keeps a copy as build/main-<venue>.pdf.

MAIN   ?= main
VENUE  ?= arxiv
FINAL  ?=

LATEX  = pdflatex -interaction=nonstopmode -halt-on-error
BIBTEX = bibtex

# Extra paperkit options, e.g. `make OPTS=panel,colorlinks neurips'.
OPTS ?=
ifeq ($(FINAL),1)
  ifeq ($(strip $(OPTS)),)
    ALLOPTS := final
  else
    ALLOPTS := final,$(OPTS)
  endif
else
  ALLOPTS := $(OPTS)
endif

ifeq ($(strip $(ALLOPTS)),)
  PKOPTS =
else
  PKOPTS = \PassOptionsToPackage{$(ALLOPTS)}{styles/paperkit}
endif

.PHONY: all arxiv arxiv1col icml neurips neurips2025 plain build example test \
        clean distclean

all: arxiv

arxiv arxiv1col icml neurips neurips2025 plain:
	@$(MAKE) --no-print-directory build VENUE=$@

build:
	$(LATEX) "$(PKOPTS)\def\pkvenue{$(VENUE)}\input{$(MAIN).tex}"
	-$(BIBTEX) $(MAIN)
	$(LATEX) "$(PKOPTS)\def\pkvenue{$(VENUE)}\input{$(MAIN).tex}"
	$(LATEX) "$(PKOPTS)\def\pkvenue{$(VENUE)}\input{$(MAIN).tex}"
	@mkdir -p build
	@cp $(MAIN).pdf build/$(MAIN)-$(VENUE).pdf
	@echo "==> $(MAIN).pdf (venue: $(VENUE)) and build/$(MAIN)-$(VENUE).pdf"

# The demo paper for the one-column venue. It reads styles/ and references.bib
# from the repository root, so it has to be compiled from its own directory.
EXAMPLE = arxiv1col-demo

example:
	cd examples && $(LATEX) $(EXAMPLE).tex \
	  && $(BIBTEX) $(EXAMPLE) \
	  && $(LATEX) $(EXAMPLE).tex \
	  && $(LATEX) $(EXAMPLE).tex
	@echo "==> examples/$(EXAMPLE).pdf"

test:
	./tests/test-paperkit.sh

clean:
	rm -f $(MAIN).aux $(MAIN).log $(MAIN).out $(MAIN).bbl $(MAIN).blg \
	      $(MAIN).fls $(MAIN).fdb_latexmk $(MAIN).synctex.gz $(MAIN).toc \
	      $(MAIN).brf $(MAIN).nav $(MAIN).snm $(MAIN).vrb
	rm -f examples/$(EXAMPLE).aux examples/$(EXAMPLE).log examples/$(EXAMPLE).out \
	      examples/$(EXAMPLE).bbl examples/$(EXAMPLE).blg examples/$(EXAMPLE).brf

distclean: clean
	rm -f $(MAIN).pdf examples/$(EXAMPLE).pdf
	rm -rf build
