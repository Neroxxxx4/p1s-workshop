// JS vanilla, progressif : sans lui, tout reste utilisable (sauf le panier).
const eur = (v) => `${v.toFixed(2)} €`;
const r2 = (v) => Math.round(v * 100) / 100;
const num = (el) => parseFloat(String(el?.value ?? "").replace(",", ".")) || 0;

// Confirmation des formulaires sensibles + anti double-envoi (double tap = 2 impressions, 2× le filament)
document.addEventListener("submit", (e) => {
  const f = e.target, msg = f.dataset.confirm;
  if (e.defaultPrevented || (msg && !confirm(msg))) return e.preventDefault();
  if (f.dataset.envoye) return e.preventDefault();
  f.dataset.envoye = "1";
});
// Retour arrière (cache du navigateur) : les formulaires redeviennent utilisables
addEventListener("pageshow", () => document.querySelectorAll("form[data-envoye]").forEach((f) => delete f.dataset.envoye));

// Sur téléphone, l'onglet actif peut être hors de l'écran dans la barre défilante
document.querySelector(".tabs .active")?.scrollIntoView({ inline: "center", block: "nearest" });

// Stock : confirmation si la bobine existe déjà (=> recharge)
const formBobine = document.getElementById("form-bobine");
formBobine?.addEventListener("submit", (e) => {
  const f = formBobine.elements;
  const id = `${f.marque.value.trim()} ${f.matiere.value} ${f.couleur.value.trim()}`;
  if (!JSON.parse(formBobine.dataset.ids).includes(id)) return;
  if (confirm(`« ${id} » existe déjà. La recharger (reste remis à la capacité) ?`)) f.remplacer.value = "1";
  else e.preventDefault();
});

// Lancement : aperçu du coût (même formule que services.cout_impression)
const formLancement = document.getElementById("form-lancement");
if (formLancement) {
  const f = formLancement.elements;
  const kw = parseFloat(formLancement.dataset.puissance);
  const maj = () => {
    const prixKg = parseFloat(f.bobine.selectedOptions[0]?.dataset.prix) || 0;
    const poids = num(f.poids) + num(f.perte);
    const h = num(f.heures) + num(f.minutes) / 60;
    const matiere = (prixKg / 1000) * poids, machine = h * (num(f.usure) + kw * num(f.kwh));
    document.getElementById("apercu-cout").textContent = eur(r2(matiere + machine));
    document.getElementById("apercu-detail").textContent = `${poids} g · filament ${eur(matiere)} + machine ${eur(machine)}`;
  };
  formLancement.addEventListener("input", maj);
  maj();
}

// Prix de vente : panier
const prix = document.getElementById("prix");
if (prix) {
  const panier = new Map();
  const range = document.getElementById("marge-range"), marge = document.getElementById("marge");
  const set = (id, txt) => (document.getElementById(id).textContent = txt);

  const maj = () => {
    const cout = r2([...panier.values()].reduce((s, p) => s + p.cout, 0));
    const m = num(marge);
    const p = r2(cout * (1 + m / 100));
    set("p-cout", eur(cout)); set("p-prix", eur(p));
    set("m-cout", eur(cout)); set("m-marge", `${m} %`); set("m-prix", eur(p)); set("m-benef", eur(r2(p - cout)));

    const lignes = [...document.querySelectorAll(".scenarios tr[data-m]")];
    const proche = lignes.reduce((a, b) => (Math.abs(b.dataset.m - m) < Math.abs(a.dataset.m - m) ? b : a));
    for (const tr of lignes) {
      const sp = r2(cout * (1 + tr.dataset.m / 100));
      tr.cells[1].textContent = eur(sp);
      tr.cells[2].textContent = eur(r2(sp - cout));
      tr.classList.toggle("proche", tr === proche);
    }

    const ul = document.getElementById("panier"), ids = document.getElementById("ids");
    ul.replaceChildren(); ids.replaceChildren();
    for (const [id, piece] of panier) {
      const li = document.createElement("li");
      li.append(Object.assign(document.createElement("span"), { textContent: piece.nom }),
                Object.assign(document.createElement("b"), { textContent: eur(piece.cout), className: "num" }));
      ul.append(li);
      ids.append(Object.assign(document.createElement("input"), { type: "hidden", name: "ids", value: id }));
    }
    document.getElementById("panier-vide").hidden = panier.size > 0;
    document.getElementById("btn-vendre").disabled = panier.size === 0;
  };

  prix.addEventListener("click", (e) => {
    const b = e.target.closest(".piece");
    if (!b) return;
    const { id, nom, cout } = b.dataset;
    panier.has(id) ? panier.delete(id) : panier.set(id, { nom, cout: parseFloat(cout) });
    b.setAttribute("aria-pressed", panier.has(id));
    maj();
  });
  range.addEventListener("input", () => { marge.value = range.value; maj(); });
  marge.addEventListener("input", () => { range.value = num(marge); maj(); });
  document.getElementById("vider-panier").addEventListener("click", () => {
    panier.clear();
    document.querySelectorAll(".piece").forEach((b) => b.setAttribute("aria-pressed", "false"));
    maj();
  });
  maj();
}
