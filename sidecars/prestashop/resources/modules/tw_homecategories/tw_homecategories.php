<?php
/**
 * TimberWorks — dynamic "shop by category" tiles for the home.
 *
 * A widget module (like ps_categorytree) so the home tiles read the live catalogue
 * at render time, localized to the current language — no baking, no regeneration
 * after a catalogue sync.
 */

if (!defined('_PS_VERSION_')) {
    exit;
}

use PrestaShop\PrestaShop\Core\Module\WidgetInterface;

class Tw_HomeCategories extends Module implements WidgetInterface
{
    /** @var array<string, array<string, string>> English category name => per-locale blurb */
    private const BLURBS = [
        'Raw Wood' => ['en' => 'Logs, blocks and raw timber to start any build.', 'fr' => 'Grumes, blocs et bois brut pour démarrer.'],
        'Processed Wood' => ['en' => 'Planks, panels and prepared wood for structure and assembly.', 'fr' => 'Planches, panneaux et bois préparé pour la structure.'],
        'Planting & Nursery' => ['en' => 'Saplings, soil and natural greenery for living builds.', 'fr' => 'Jeunes plants, terre et végétation naturelle.'],
        'Structural Components' => ['en' => 'Stairs, slabs, fences and gates, prefabricated.', 'fr' => 'Escaliers, dalles, clôtures et portails préfabriqués.'],
        'Access & Closures' => ['en' => 'Doors, gates and trapdoors.', 'fr' => 'Portes, portails et trappes.'],
        'Wood Hardware' => ['en' => 'Fixings, fittings and finishing hardware.', 'fr' => 'Fixations, ferrures et quincaillerie de finition.'],
        'Signage' => ['en' => 'Signs and wall-mounted markers.', 'fr' => 'Panneaux et marqueurs muraux.'],
        'Storage & Workshop' => ['en' => 'Chests, barrels, crafting stations and scaffolding.', 'fr' => 'Coffres, tonneaux, établis et échafaudages.'],
        'Bundles' => ['en' => 'Ready-to-build construction kits.', 'fr' => 'Kits de construction prêts à monter.'],
    ];

    public function __construct()
    {
        $this->name = 'tw_homecategories';
        $this->version = '1.0.0';
        $this->author = 'Archipel Labs';
        $this->tab = 'front_office_features';
        $this->need_instance = 0;
        $this->ps_versions_compliancy = ['min' => '1.7.0.0', 'max' => _PS_VERSION_];

        parent::__construct();

        $this->displayName = 'TimberWorks home categories';
        $this->description = 'Dynamic shop-by-category tiles for the home.';
    }

    public function install()
    {
        return parent::install() && $this->registerHook('displayHome');
    }

    public function renderWidget($hookName = null, array $configuration = [])
    {
        $this->smarty->assign($this->getWidgetVariables($hookName, $configuration));

        return $this->fetch('module:tw_homecategories/views/templates/widget/tiles.tpl');
    }

    public function getWidgetVariables($hookName = null, array $configuration = [])
    {
        $idLang = (int) $this->context->language->id;
        $iso = $this->context->language->iso_code;
        $idDefault = (int) Configuration::get('PS_LANG_DEFAULT');
        $home = (int) Configuration::get('PS_HOME_CATEGORY');

        // English names are the stable key into the blurb map; display names follow
        // the current language.
        $englishNames = [];
        foreach (Category::getChildren($home, $idDefault, true) as $row) {
            $englishNames[(int) $row['id_category']] = $row['name'];
        }

        $categories = [];
        foreach (Category::getChildren($home, $idLang, true) as $row) {
            $id = (int) $row['id_category'];
            $blurbs = self::BLURBS[$englishNames[$id] ?? ''] ?? [];
            $categories[] = [
                'name' => $row['name'],
                'url' => $this->context->link->getCategoryLink($id),
                'blurb' => $blurbs[$iso] ?? ($blurbs['en'] ?? ''),
            ];
        }

        return [
            'tw_categories' => $categories,
            'tw_title' => $iso === 'fr' ? 'Acheter par catégorie' : 'Shop by category',
        ];
    }
}
