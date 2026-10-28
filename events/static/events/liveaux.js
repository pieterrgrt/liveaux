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

  // --- Social: share buttons -------------------------------------------------------------
  // The phone's share sheet where there is one; otherwise the link goes to the clipboard.
  // The button stays hidden without the script, so nothing on the page is broken without it.
  function setUpShare() {
    var canShare = typeof navigator.share === "function";

    function writeText(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
      return new Promise(function (resolve, reject) {
        var field = document.createElement("textarea");
        field.value = text;
        field.setAttribute("readonly", "");
        field.style.position = "fixed";
        field.style.opacity = "0";
        document.body.appendChild(field);
        field.select();
        var ok = false;
        try { ok = document.execCommand("copy"); } catch (e) {}
        field.remove();
        (ok ? resolve : reject)();
      });
    }

    document.querySelectorAll("[data-share]").forEach(function (box) {
      var button = box.querySelector("button");
      var status = box.querySelector(".share-status");
      var url = box.dataset.shareUrl || window.location.href;
      var title = box.dataset.shareTitle || document.title;
      var timer;
      box.hidden = false;

      function say(text) {
        status.textContent = text;
        clearTimeout(timer);
        timer = setTimeout(function () { status.textContent = ""; }, 2500);
      }

      function copy() {
        writeText(url).then(
          function () { say("Link copied"); },
          function () { say("Couldn't copy the link"); }
        );
      }

      button.addEventListener("click", function () {
        if (!canShare) return copy();
        navigator.share({ title: title, url: url }).catch(function (error) {
          // Closing the share sheet is not an error; anything else falls back to copying.
          if (error && error.name !== "AbortError") copy();
        });
      });
    });
  }
  // --- end social ---------------------------------------------------------------------------

  function ready() {
    placeArrival();
    setUpChoice();
    setUpShare();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready);
  } else {
    ready();
  }
})();
