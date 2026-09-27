/* 사부작 디자인(Figma Make, 사부작 디자인/src/App.tsx의 WorldMap 컴포넌트)을
 * 그대로 옮긴 바닐라 JS 버전. React 대신 d3 + topojson-client로 같은
 * SVG를 그린다 (투영법, 대륙 색상, antimeridian 언랩 로직 전부 동일).
 *
 * 필요한 전역: d3(+ d3-geo-projection로 확장된 d3.geoMiller), topojson
 * (base.html에서 CDN으로 로드).
 */
(function () {
  "use strict";

  var MAP_W = 800;
  var MAP_H = 460;

  // ISO 3166-1 numeric → 대륙 그룹 (countries-110m.json의 feature id 기준)
  var CC = {};
  [28, 32, 44, 52, 60, 68, 76, 84, 92, 124, 136, 152, 170, 188, 192, 212, 214,
    218, 222, 238, 254, 304, 308, 312, 320, 328, 332, 340, 388, 474, 484, 500,
    531, 533, 534, 535, 558, 591, 600, 604, 630, 659, 660, 662, 663, 666, 670,
    740, 780, 796, 840, 850, 858, 862].forEach(function (id) { CC[id] = "americas"; });
  [8, 20, 40, 56, 70, 100, 112, 191, 196, 203, 208, 233, 234, 246, 248, 250,
    276, 292, 300, 336, 348, 352, 372, 380, 428, 438, 440, 442, 470, 492, 498,
    499, 528, 578, 616, 620, 642, 674, 688, 703, 705, 724, 752, 756, 804, 807,
    826, 833].forEach(function (id) { CC[id] = "europe"; });
  [48, 275, 364, 368, 376, 400, 414, 422, 512, 634, 682, 760, 784, 792, 818,
    887, 12, 24, 72, 86, 108, 120, 132, 140, 148, 174, 175, 178, 180, 204, 226,
    231, 232, 262, 266, 270, 288, 324, 384, 404, 426, 430, 434, 450, 454, 466,
    478, 480, 504, 508, 516, 562, 566, 638, 646, 654, 678, 686, 690, 694, 706,
    710, 716, 728, 729, 732, 748, 768, 788, 800, 834, 854, 894]
    .forEach(function (id) { CC[id] = "middleeast"; });
  [4, 31, 50, 51, 64, 96, 104, 116, 144, 156, 158, 268, 344, 356, 360, 392,
    398, 408, 410, 417, 418, 446, 458, 462, 496, 524, 586, 608, 626, 643, 702,
    704, 762, 764, 795, 860].forEach(function (id) { CC[id] = "asia"; });
  [16, 36, 90, 162, 166, 184, 242, 258, 296, 316, 334, 520, 540, 548, 554, 570,
    574, 580, 583, 584, 585, 598, 612, 776, 798, 876, 882]
    .forEach(function (id) { CC[id] = "oceania"; });

  var CONTINENT_COLOR = {
    americas: "#5cb88b",
    europe: "#6b8ec4",
    middleeast: "#9b6ec2",
    asia: "#c4a05a",
    oceania: "#c07878",
  };

  // 대륙 영문 id → 백엔드(CONTINENT_DB_VALUES) 한글 라벨
  var CONTINENT_KO = {
    americas: "아메리카",
    europe: "유럽",
    middleeast: "중동·아프리카",
    asia: "아시아",
    oceania: "오세아니아",
  };

  function getCountryContinent(numericId) {
    return CC[numericId] || null;
  }

  // ── antimeridian 언랩 (feature 중심 경도로 서/동반구 판단) ──────────────────
  function featureCentroidLon(geom) {
    var lons = [];
    if (geom.type === "Polygon") {
      geom.coordinates[0].forEach(function (p) { lons.push(p[0]); });
    } else if (geom.type === "MultiPolygon") {
      var largest = geom.coordinates.reduce(function (a, b) {
        return a[0].length > b[0].length ? a : b;
      });
      largest[0].forEach(function (p) { lons.push(p[0]); });
    }
    if (!lons.length) return 0;
    return lons.reduce(function (a, b) { return a + b; }, 0) / lons.length;
  }

  function unwrapRing(ring, homeIsWest) {
    var hasCross = ring.some(function (pt, i) {
      return i > 0 && Math.abs(pt[0] - ring[i - 1][0]) > 180;
    });
    if (!hasCross) return ring;
    if (homeIsWest) {
      return ring.map(function (p) { return p[0] > 90 ? [p[0] - 360, p[1]] : p; });
    }
    return ring.map(function (p) { return p[0] < -90 ? [p[0] + 360, p[1]] : p; });
  }

  function unwrapGeometry(geom, homeIsWest) {
    if (geom.type === "Polygon") {
      return { type: "Polygon", coordinates: geom.coordinates.map(function (r) { return unwrapRing(r, homeIsWest); }) };
    }
    if (geom.type === "MultiPolygon") {
      return {
        type: "MultiPolygon",
        coordinates: geom.coordinates.map(function (poly) {
          return poly.map(function (r) { return unwrapRing(r, homeIsWest); });
        }),
      };
    }
    return geom;
  }

  function renderWorldMap(container, options) {
    options = options || {};
    var onSelect = options.onSelect || function () {};
    var dataUrl = options.dataUrl;

    fetch(dataUrl)
      .then(function (res) { return res.json(); })
      .then(function (topo) {
        var allFeatures = topojson.feature(topo, topo.objects.countries).features;
        var noAntarctica = allFeatures.filter(function (f) { return f.id !== "010"; });
        var stitched = noAntarctica.map(function (f) {
          var centLon = featureCentroidLon(f.geometry);
          return Object.assign({}, f, { geometry: unwrapGeometry(f.geometry, centLon < 0) });
        });
        var filteredFC = { type: "FeatureCollection", features: stitched };

        var projection = d3.geoMiller().rotate([-12, 0, 0]).fitSize([MAP_W, MAP_H], filteredFC);
        var path = d3.geoPath(projection);

        var svg = d3.select(container).append("svg")
          .attr("viewBox", "0 0 " + MAP_W + " " + MAP_H)
          .attr("width", "100%")
          .attr("height", "auto")
          .style("display", "block")
          .style("background", "transparent");

        var active = null;

        function fillFor(continent, hovered) {
          if (!continent) return "transparent";
          var base = CONTINENT_COLOR[continent];
          if (active === continent) return base;
          if (hovered === continent) return base + "ee";
          return base + "88";
        }

        var paths = svg.selectAll("path")
          .data(stitched)
          .join("path")
          .attr("d", path)
          .attr("stroke", "none")
          .attr("fill", function (d) { return fillFor(getCountryContinent(Number(d.id)), null); })
          .style("cursor", function (d) { return getCountryContinent(Number(d.id)) ? "pointer" : "default"; })
          .style("transition", "fill 0.12s");

        function repaint(hoveredGroup) {
          paths.attr("fill", function (d) { return fillFor(getCountryContinent(Number(d.id)), hoveredGroup); });
        }

        paths
          .on("mouseenter", function (event, d) {
            var c = getCountryContinent(Number(d.id));
            if (c) repaint(c);
          })
          .on("mouseleave", function () { repaint(null); })
          .on("click", function (event, d) {
            var c = getCountryContinent(Number(d.id));
            if (!c) return;
            // 강조 상태 토글은 _worldMapSetActive 하나에서만 처리 (여기서는 토글하지 않음)
            onSelect(c, CONTINENT_KO[c]);
          });

        // 바깥에서 범례 클릭으로도 강조 상태를 맞출 수 있도록 노출
        container._worldMapSetActive = function (continentEn) {
          active = active === continentEn ? null : continentEn;
          repaint(null);
        };
      })
      .catch(function (err) {
        console.error("세계 지도 데이터를 불러오지 못했습니다:", err);
        container.innerHTML = '<p class="page-desc">지도를 불러오지 못했습니다.</p>';
      });
  }

  window.SabuzakWorldMap = {
    render: renderWorldMap,
    CONTINENT_COLOR: CONTINENT_COLOR,
    CONTINENT_KO: CONTINENT_KO,
  };
})();
