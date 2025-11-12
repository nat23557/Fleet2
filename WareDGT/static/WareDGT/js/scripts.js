document.addEventListener("DOMContentLoaded", () => {
  const SIDEBAR_OPEN_CLASS = "mobile-sidebar-open";

  //
  // 1) Header dropdowns
  //
  const dropdowns = [
    { btn: "erp-header__notif-btn", menu: "erp-header__notif-menu" },
    { btn: "erp-header__msg-btn",   menu: "erp-header__msg-menu" },
    { btn: "erp-header__settings-btn", menu: "erp-header__settings-menu" },
    { btn: "erp-header__mobile-menu-btn", menu: "erp-header__mobile-menu-list" },
  ];
  let openMenu = null;

  dropdowns.forEach(({ btn, menu }) => {
    const btnElem  = document.getElementById(btn);
    const menuElem = document.getElementById(menu);
    if (!btnElem || !menuElem) return;

    btnElem.addEventListener("click", (e) => {
      e.stopPropagation();
      // hide any other open menu
      dropdowns.forEach(({ menu: otherMenu }) => {
        if (otherMenu !== menu) {
          const otherElem = document.getElementById(otherMenu);
          if (otherElem) otherElem.style.display = "none";
        }
      });
      // toggle this one
      menuElem.style.display = (menuElem.style.display === "block") ? "none" : "block";
      openMenu = menuElem.style.display === "block" ? menuElem : null;
    });
  });

  //
  // 2) Sidebar toggle
  //
  const sidebarToggle = document.getElementById("erp-sidebar-toggle");
  const sidebarClose  = document.getElementById("mobile-sidebar-close");
  const sidebarCloseBtn = document.getElementById("mobile-sidebar-close-btn");
  const backdrop      = document.getElementById("sidebar-backdrop");

  function openSidebar() {
    document.body.classList.add(SIDEBAR_OPEN_CLASS);
  }

  function closeSidebar() {
    document.body.classList.remove(SIDEBAR_OPEN_CLASS);
  }

  function clickedOutsideSidebar(target) {
    return (
      document.body.classList.contains(SIDEBAR_OPEN_CLASS) &&
      !target.closest("#mobile-sidebar") &&
      !target.closest("#erp-sidebar-toggle")
    );
  }

  if (sidebarToggle) {
    sidebarToggle.addEventListener("click", (e) => {
      if (window.innerWidth <= 900) {
        e.preventDefault();
        if (document.body.classList.contains(SIDEBAR_OPEN_CLASS)) {
          closeSidebar();
        } else {
          openSidebar();
        }
      }
    });
  }
  if (sidebarClose) sidebarClose.addEventListener("click", closeSidebar);
  if (sidebarCloseBtn) sidebarCloseBtn.addEventListener("click", closeSidebar);
  if (backdrop) backdrop.addEventListener("click", closeSidebar);

  //
  // 3) Close sidebar on nav link click (mobile)
  //
  document.querySelectorAll("#mobile-sidebar .erp-sidebar__link").forEach(link => {
    link.addEventListener("click", closeSidebar);
  });

  //
  // 4) Global click – close dropdowns and sidebar if clicking outside
  //
  document.addEventListener("click", (e) => {
    // hide all dropdown menus
    dropdowns.forEach(({ menu }) => {
      const menuElem = document.getElementById(menu);
      if (menuElem) menuElem.style.display = "none";
    });
    openMenu = null;

    // close mobile sidebar if clicking outside
    if (clickedOutsideSidebar(e.target)) {
      closeSidebar();
    }
  });

  //
  // 5) Close on Escape
  //
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      // hide sidebar
      if (document.body.classList.contains(SIDEBAR_OPEN_CLASS)) {
        closeSidebar();
      }
      // hide any open dropdown
      dropdowns.forEach(({ menu }) => {
        const menuElem = document.getElementById(menu);
        if (menuElem) menuElem.style.display = "none";
      });
      openMenu = null;
    }
  });

  //
  // 6) Auto-dismiss flash messages
  //
  const msgBox = document.getElementById("messages");
  if (msgBox) {
    setTimeout(() => msgBox.remove(), 10000);
  }

  //
  // 7) Helper for showing messages programmatically
  //
  window.showMessage = function (level, text) {
    let box = document.getElementById("messages");
    if (!box) {
      box = document.createElement("div");
      box.id = "messages";
      box.className = "erp-messages";
      document.body.appendChild(box);
    }
    const msg = document.createElement("div");
    msg.className = "erp-message " + (level || "success");
    msg.textContent = text;
    box.appendChild(msg);
    setTimeout(() => {
      msg.remove();
      if (!box.children.length) box.remove();
    }, 10000);
  };
});
