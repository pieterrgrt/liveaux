// liveaux: the little motion that needs a script. Everything works without it.
(function () {
  "use strict";

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");

  // Coming in through the e: the colour closes in on the e of the logo in the header.
  function placeArrival() {
    var root = document.documentElement;
    if (!root.dataset.arrive) return;
    var e = document.querySelector(".wordmark .logo-e");
    if (e) {
      var box = e.getBoundingClientRect();
      root.style.setProperty("--arrive-x", box.left + box.width / 2 + "px");
      root.style.setProperty("--arrive-y", box.top + box.height / 2 + "px");
    }
    setTimeout(function () { delete root.dataset.arrive; }, 1000);
  }

  // The front page: point at a side and the e leans its way; tap it and you zoom into the e.
  function setUpChoice() {
    var choose = document.querySelector(".choose");
    if (!choose) return;
    var logo = choose.querySelector(".choose-logo .logo");

    choose.querySelectorAll("[data-choose]").forEach(function (link) {
      var side = link.dataset.choose;
      link.addEventListener("pointerenter", function () { choose.dataset.hover = side; });
      link.addEventListener("pointerleave", function () { delete choose.dataset.hover; });
      link.addEventListener("focus", function () { choose.dataset.hover = side; });
      link.addEventListener("blur", function () { delete choose.dataset.hover; });
      link.addEventListener("click", function (event) {
        if (reduce.matches || event.metaKey || event.ctrlKey || event.shiftKey || event.button) return;
        event.preventDefault();
        zoom(side, link.href);
      });
    });

    function zoom(side, href) {
      // The middle of the e's bar, as it leans: zooming there fills the screen with the e.
      var box = logo.getBoundingClientRect();
      var x = (138.5 / 358) * box.width;
      var y = (69 / 136) * box.height;
      logo.style.transformOrigin = x + "px " + y + "px";
      choose.dataset.chosen = side;
      delete choose.dataset.hover;
      // Force a style flush so the origin applies before the zoom starts.
      void logo.getBoundingClientRect();
      choose.classList.add("is-zooming");
      try { sessionStorage.setItem("liveaux-arrive", side); } catch (e) {}
      setTimeout(function () { window.location.href = href; }, 800);
    }

    // Back from the next page (bfcache): show the choice again, not the zoomed-in e.
    window.addEventListener("pageshow", function (event) {
      if (event.persisted) {
        choose.classList.remove("is-zooming");
        delete choose.dataset.chosen;
      }
    });
  }

  function ready() {
    placeArrival();
    setUpChoice();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready);
  } else {
    ready();
  }
})();
