# California topo puzzle — regeneration graph (D12 automation contract).
#
#   make            rebuild whatever is stale (config, overrides, scripts,
#                   upstream artifacts all tracked as dependencies)
#   make p4         one stage (p0/p1/p2/p15/p15b/p4)
#   make -n         show what would rebuild
#
# Change any region aspect (config.toml knob or a new overrides/*.geojson
# markup) and `make` brings every downstream artifact current. Written for
# the stock macOS make (3.81): multi-output stages use one canonical
# target; sibling outputs ride along via empty recipes.

UV       := uv run
PIPE     := pipeline
OVERRIDES := $(wildcard overrides/*.geojson)
COMMON   := config.toml $(OVERRIDES) $(PIPE)/p1_regions.py
DEM      := data/dem_ca_albers_250m.npy

.PHONY: all p0 p1 p2 p2layout p15 p15b p4 p5 rose_coupon
all: p1 p2 p2layout p15 p15b p4 p5

# ---- P0: statewide 250 m heightfield (slow; rebuilds only if p0 changes)
p0: $(DEM)
$(DEM): $(PIPE)/p0_build_dem.py
	$(UV) $(PIPE)/p0_build_dem.py

# ---- P1: statewide region render
p1: out/p1_final.png
out/p1_final.png: $(PIPE)/p1_final_render.py $(COMMON) $(DEM)
	$(UV) $(PIPE)/p1_final_render.py

# ---- P2a: Census land authority (downloads cached in data/)
data/p2_land.npz: $(PIPE)/p2_land.py config.toml $(DEM)
	$(UV) $(PIPE)/p2_land.py
# ride-along output (touch keeps its mtime ordered after the canonical
# target, so `make -n` agrees with `make`)
data/p2_borders.geojson: data/p2_land.npz
	@touch $@

# ---- P2b: region vectorization (canonical + smooth flavors)
p2: data/p2_regions_smooth.geojson
data/p2_regions_smooth.geojson: $(PIPE)/p2_vectorize.py $(COMMON) $(DEM) \
		data/p2_land.npz data/p2_borders.geojson
	$(UV) $(PIPE)/p2_vectorize.py
data/p2_regions.geojson: data/p2_regions_smooth.geojson
	@touch $@

# ---- P2 layout drawing (consumes [output].total_ns_mm)
p2layout: out/p2_layout.png
out/p2_layout.png: $(PIPE)/p2_layout.py $(COMMON) \
		data/p2_regions_smooth.geojson data/p2_borders.geojson data/p2_land.npz
	$(UV) $(PIPE)/p2_layout.py

# ---- P1.5: statewide engraved slab (grooves from P2 vectors)
p15: out/p15_ca_engraved_150mm.stl
out/p15_ca_engraved_150mm.stl: $(PIPE)/p15_engraved.py $(PIPE)/mesh_common.py \
		$(COMMON) $(DEM) data/p2_regions_smooth.geojson data/p2_borders.geojson
	$(UV) $(PIPE)/p15_engraved.py

# ---- P1.5b: Bay Area inset (zoom-11 terrain; kept regenerable though
# ---- ahl skipped its print)
p15b: out/p15b_vallejo_inset.stl
out/p15b_vallejo_inset.stl: $(PIPE)/p15b_vallejo_inset.py $(PIPE)/dem_hires.py \
		$(PIPE)/p15_engraved.py $(PIPE)/mesh_common.py $(COMMON) $(DEM) \
		data/p2_regions_smooth.geojson
	$(UV) $(PIPE)/p15b_vallejo_inset.py

# ---- P4 v2: Bay Area mini-frame coupon (tray frame 3MF + 2 pieces)
p4: out/p4_mini/frame.3mf
out/p4_mini/frame.3mf: $(PIPE)/p4_bay_coupon.py $(PIPE)/version_stamp.py \
		$(PIPE)/mesh_common.py $(PIPE)/compass_art.py $(COMMON) $(DEM) \
		data/p2_land.npz assets/compass.svg config.toml
	$(UV) $(PIPE)/p4_bay_coupon.py

# ---- P5: FULL final product (4-color frame 3MF + 3 pieces + preview)
p5: out/p5/frame.3mf
out/p5/frame.3mf: $(PIPE)/p5_final.py $(PIPE)/p4_bay_coupon.py \
		$(PIPE)/version_stamp.py $(PIPE)/mesh_common.py \
		$(PIPE)/compass_art.py $(PIPE)/key_panel.py $(COMMON) $(DEM) \
		data/p2_land.npz assets/compass.svg config.toml
	$(UV) $(PIPE)/p5_final.py
# ride-alongs of the p5 stage (see the make 3.81 note at the top)
out/p5/key.stl out/p5/key_insert.pdf: out/p5/frame.3mf
	@touch $@

# ---- Rose-only test coupon: just the compass-rose corner (water disk +
# ---- raised ink), to test-print a rose design tweak without the whole
# ---- frame. No DEM/region deps -- imports p4_bay_coupon for shared
# ---- config/constants + the 3MF writer only.
rose_coupon: out/rose_coupon/rose_coupon.3mf
out/rose_coupon/rose_coupon.3mf: $(PIPE)/rose_coupon.py $(PIPE)/p4_bay_coupon.py \
		$(PIPE)/compass_art.py $(PIPE)/version_stamp.py config.toml \
		assets/compass.svg
	$(UV) $(PIPE)/rose_coupon.py
