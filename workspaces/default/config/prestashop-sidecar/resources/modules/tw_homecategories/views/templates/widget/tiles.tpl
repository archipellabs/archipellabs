{if $tw_categories}
  <section id="shop-by-category" class="tw-cats">
    <div class="container">
      <h2 class="tw-section-title">{$tw_title}</h2>
      <div class="tw-cats__grid">
        {foreach from=$tw_categories item=cat}
          <a class="tw-cat" href="{$cat.url}">
            <span class="tw-cat__name">{$cat.name}</span>
            {if $cat.blurb}<span class="tw-cat__blurb">{$cat.blurb}</span>{/if}
          </a>
        {/foreach}
      </div>
    </div>
  </section>
{/if}
