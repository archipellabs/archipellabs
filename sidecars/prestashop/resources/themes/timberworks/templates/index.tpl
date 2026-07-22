{**
 * TimberWorks home — child-theme override of Hummingbird's index.tpl.
 * Brand sections are static; {$HOOK_HOME} keeps the dynamic ps_featuredproducts
 * block; the category tiles are driven by the generated data partial
 * (_partials/tw-home-categories.tpl, written by the GenerateHomeCategories step).
 *}
{extends file=$layout}

{block name='breadcrumb'}{/block}

{block name='content_columns'}
  {block name='left_column'}{/block}

  {block name='content_wrapper'}
    <div id="center-column" class="center-column page">
      {hook h="displayContentWrapperTop"}

      {block name='content'}
        <div id="content" class="page-content page-content--home tw-home">

          {* ---- Hero ---- *}
          <section class="tw-hero">
            <div class="container tw-hero__inner">
              <p class="tw-hero__eyebrow">{if $language.iso_code == 'fr'}Distribution spécialisée de bois{else}Specialized wood distribution{/if}</p>
              <h1 class="tw-hero__title">{if $language.iso_code == 'fr'}Du bois et des composants, conçus pour s'assembler.{else}Wood and components, built to fit together.{/if}</h1>
              <p class="tw-hero__subtitle">{if $language.iso_code == 'fr'}Des grumes brutes aux kits prêts à monter — un catalogue ciblé de matériaux bois pour les constructeurs, architectes et makers. Un seul domaine, bien fait.{else}From raw logs to ready-to-assemble kits — a focused catalogue of wood materials for builders, architects and makers. One domain, done well.{/if}</p>
              <div class="tw-hero__actions">
                <a class="btn btn-primary btn-lg" href="#shop-by-category">{if $language.iso_code == 'fr'}Parcourir le catalogue{else}Browse the catalogue{/if}</a>
                <a class="btn btn-outline-primary btn-lg" href="#construction-kits">{if $language.iso_code == 'fr'}Voir les kits de construction{else}See construction kits{/if}</a>
              </div>
            </div>
          </section>

          {* ---- Shop by category (live widget — reads the catalogue at render time) ---- *}
          {widget name='tw_homecategories'}

          {* ---- Featured materials (ps_featuredproducts via displayHome) ---- *}
          <section class="tw-featured">
            <div class="container">
              {$HOOK_HOME nofilter}
            </div>
          </section>

          {* ---- Why TimberWorks ---- *}
          <section class="tw-why">
            <div class="container">
              <h2 class="tw-section-title">{if $language.iso_code == 'fr'}Pourquoi TimberWorks{else}Why TimberWorks{/if}</h2>
              <div class="tw-why__grid">
                <div class="tw-why__item">
                  <h3>{if $language.iso_code == 'fr'}Un catalogue ciblé{else}A focused catalogue{/if}</h3>
                  <p>{if $language.iso_code == 'fr'}Uniquement du bois et des matériaux dérivés. Sans le bruit d'une marketplace généraliste.{else}Only wood and wood-based materials. None of the noise of a generic marketplace.{/if}</p>
                </div>
                <div class="tw-why__item">
                  <h3>{if $language.iso_code == 'fr'}Un réseau de fournisseurs sélectionnés{else}A curated supplier network{/if}</h3>
                  <p>{if $language.iso_code == 'fr'}Issus de scieries spécialisées et de partenaires menuisiers — OakHeart Forestry, Voxel Carpentry Works, et plus.{else}Sourced from specialist mills and carpentry partners — OakHeart Forestry, Voxel Carpentry Works and more.{/if}</p>
                </div>
                <div class="tw-why__item">
                  <h3>{if $language.iso_code == 'fr'}Des composants qui s'assemblent{else}Components that match{/if}</h3>
                  <p>{if $language.iso_code == 'fr'}Pièces et kits conçus pour assembler des structures cohérentes et reproductibles.{else}Parts and kits designed to assemble into consistent, repeatable structures.{/if}</p>
                </div>
                <div class="tw-why__item">
                  <h3>{if $language.iso_code == 'fr'}Pensé pour le chantier{else}Built for the site{/if}</h3>
                  <p>{if $language.iso_code == 'fr'}Specs et conseils adaptés aux vrais projets de construction.{else}Specs and guidance tuned to real construction projects.{/if}</p>
                </div>
              </div>
            </div>
          </section>

          {* ---- Construction kits ---- *}
          <section id="construction-kits" class="tw-kits">
            <div class="container tw-kits__inner">
              <h2 class="tw-kits__title">{if $language.iso_code == 'fr'}Construisez plus vite avec les kits{else}Build faster with construction kits{/if}</h2>
              <p class="tw-kits__text">{if $language.iso_code == 'fr'}Des éléments compatibles, regroupés et prêts à monter : Cabin Starter Kit, Watchtower Kit, Tea House Kit, Dock Construction Kit.{else}Compatible elements, grouped and ready to assemble: Cabin Starter Kit, Watchtower Kit, Tea House Kit, Dock Construction Kit.{/if}</p>
              <a class="btn btn-primary" href="#shop-by-category">{if $language.iso_code == 'fr'}Voir tous les kits{else}See all kits{/if}</a>
            </div>
          </section>

        </div>
      {/block}

      {hook h="displayContentWrapperBottom"}
    </div>
  {/block}

  {block name='right_column'}{/block}
{/block}
