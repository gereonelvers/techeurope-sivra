import { PrismaClient } from "@prisma/client";
import { faker } from "@faker-js/faker";

const prisma = new PrismaClient();

// ---------------------------------------------------------------------------
// Deterministic catalog definition.
// ---------------------------------------------------------------------------

const SITES = ["site-a", "site-b", "site-c"] as const;
const CONDITIONS = ["New", "Like New", "Good", "Fair"] as const;
const CITIES = ["München", "Berlin", "Hamburg", "Köln", "Frankfurt"] as const;

// Per category: brands, model name pool, and plausible price range in EUR.
interface CategoryDef {
  category: string;
  brands: string[];
  models: string[];
  priceMin: number; // euros
  priceMax: number; // euros
  descriptors: string[];
}

const CATALOG: CategoryDef[] = [
  {
    category: "Bikes",
    brands: ["Canyon", "Cube", "Trek", "Specialized", "Giant", "Cannondale", "Bulls"],
    models: ["Endurace", "Aeroad", "Reaction", "Stereo", "Domane", "Marlin", "Tarmac", "Rockhopper", "Talon", "Defy", "Synapse", "Copperhead"],
    priceMin: 180,
    priceMax: 3200,
    descriptors: ["carbon frame", "hydraulic disc brakes", "Shimano groupset", "tubeless ready", "size M", "size L", "barely ridden"],
  },
  {
    category: "Laptops",
    brands: ["Apple", "Dell", "Lenovo", "HP", "Asus", "Acer", "Microsoft"],
    models: ["MacBook Pro", "MacBook Air", "XPS 13", "XPS 15", "ThinkPad X1", "ThinkPad T14", "Spectre x360", "ZenBook", "Swift 3", "Surface Laptop"],
    priceMin: 240,
    priceMax: 2600,
    descriptors: ["16GB RAM", "512GB SSD", "M2 chip", "Core i7", "Ryzen 7", "great battery", "small dent", "with charger"],
  },
  {
    category: "Phones",
    brands: ["Apple", "Samsung", "Google", "OnePlus", "Xiaomi", "Sony"],
    models: ["iPhone 13", "iPhone 14", "iPhone 15", "Galaxy S22", "Galaxy S23", "Pixel 7", "Pixel 8", "Nord 3", "13 Pro", "Xperia 5"],
    priceMin: 120,
    priceMax: 1300,
    descriptors: ["128GB", "256GB", "unlocked", "minor scratches", "battery 92%", "with case", "boxed"],
  },
  {
    category: "Cameras",
    brands: ["Canon", "Nikon", "Sony", "Fujifilm", "Panasonic", "Olympus"],
    models: ["EOS R6", "EOS 90D", "Z6 II", "D7500", "Alpha A7 III", "Alpha A6400", "X-T4", "X100V", "Lumix G9", "OM-D E-M10"],
    priceMin: 160,
    priceMax: 2400,
    descriptors: ["body only", "with kit lens", "low shutter count", "4K video", "full frame", "includes bag", "two batteries"],
  },
  {
    category: "Furniture",
    brands: ["IKEA", "Vitra", "USM", "String", "Hay", "Muji", "BoConcept"],
    models: ["Eames Chair", "Billy Shelf", "Malm Desk", "Haller Sideboard", "Pocket Shelf", "About A Chair", "Soft Sofa", "Poäng", "Kallax", "Lack Table"],
    priceMin: 35,
    priceMax: 1800,
    descriptors: ["oak veneer", "great condition", "some wear", "easy to assemble", "pickup only", "modular", "white"],
  },
  {
    category: "Audio",
    brands: ["Sonos", "Bose", "Sennheiser", "Sony", "JBL", "Bang & Olufsen", "Marshall"],
    models: ["One SL", "QuietComfort 45", "HD 660S", "WH-1000XM5", "Charge 5", "Beoplay H9", "Stanmore II", "Move", "Momentum 4", "Era 100"],
    priceMin: 45,
    priceMax: 1100,
    descriptors: ["noise cancelling", "boxed", "barely used", "wireless", "with cable", "great bass", "smart speaker"],
  },
];

const ITEMS_PER_SITE = 250; // base items shared across all 3 sites

interface BaseItem {
  baseItemId: number;
  title: string;
  category: string;
  brand: string;
  condition: string;
  priceCents: number;
  city: string;
  sellerName: string;
  sellerRating: number;
  description: string;
}

function buildBaseItems(): BaseItem[] {
  // Re-seed before generation so output is byte-for-byte deterministic.
  faker.seed(42);

  const items: BaseItem[] = [];

  for (let i = 0; i < ITEMS_PER_SITE; i++) {
    const baseItemId = i + 1;
    const def = faker.helpers.arrayElement(CATALOG);
    const brand = faker.helpers.arrayElement(def.brands);
    const model = faker.helpers.arrayElement(def.models);
    const condition = faker.helpers.arrayElement([...CONDITIONS]);
    const city = faker.helpers.arrayElement([...CITIES]);

    const priceEuros = faker.number.int({
      min: def.priceMin,
      max: def.priceMax,
    });
    const priceCents = priceEuros * 100;

    const sellerName = faker.person.fullName();
    const sellerRating = Number(
      faker.number.float({ min: 4.0, max: 5.0, fractionDigits: 1 }).toFixed(1),
    );

    const descriptor = faker.helpers.arrayElement(def.descriptors);
    const descriptor2 = faker.helpers.arrayElement(def.descriptors);
    const title = `${brand} ${model}`;
    const description = `${condition} ${brand} ${model}. ${capitalize(
      descriptor,
    )}, ${descriptor2}. Located in ${city}. ${faker.lorem.sentence()}`;

    items.push({
      baseItemId,
      title,
      category: def.category,
      brand,
      condition,
      priceCents,
      city,
      sellerName,
      sellerRating,
      description,
    });
  }

  return items;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

async function main() {
  console.log("Seeding marketplace database (deterministic, faker.seed(42))…");

  // Clean slate so reseeding is idempotent.
  await prisma.event.deleteMany();
  await prisma.episode.deleteMany();
  await prisma.listing.deleteMany();

  const baseItems = buildBaseItems();

  // Insert one row per (site, baseItem): same logical inventory on all 3 sites.
  const rows = SITES.flatMap((site) =>
    baseItems.map((item) => ({
      site,
      baseItemId: item.baseItemId,
      title: item.title,
      category: item.category,
      brand: item.brand,
      condition: item.condition,
      priceCents: item.priceCents,
      currency: "EUR",
      city: item.city,
      sellerName: item.sellerName,
      sellerRating: item.sellerRating,
      // imageUrl uses the row id; we don't know it pre-insert, so we use a
      // deterministic seed derived from site + baseItemId instead, which keeps
      // images stable across reseeds.
      imageUrl: `https://picsum.photos/seed/${site}-${item.baseItemId}/400/300`,
      description: item.description,
    })),
  );

  await prisma.listing.createMany({ data: rows });

  const total = await prisma.listing.count();
  const perSite = await Promise.all(
    SITES.map(async (s) => ({
      site: s,
      count: await prisma.listing.count({ where: { site: s } }),
    })),
  );

  console.log(`Inserted ${total} listings.`);
  for (const p of perSite) {
    console.log(`  ${p.site}: ${p.count} listings`);
  }

  // Quick distribution sanity print.
  const byCategory = await prisma.listing.groupBy({
    by: ["category"],
    where: { site: "site-a" },
    _count: { _all: true },
  });
  console.log("Category distribution (site-a):");
  for (const c of byCategory) {
    console.log(`  ${c.category}: ${c._count._all}`);
  }

  console.log("Seed complete.");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
