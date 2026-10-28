export const state = { user: null, users: [], status: null, library: null };
export const display = {
  load() { try { return JSON.parse(localStorage.getItem("cadence.display") || "{}"); } catch (e) { return {}; } },
  save(v) { try { localStorage.setItem("cadence.display", JSON.stringify(v)); } catch (e) {} },
};
