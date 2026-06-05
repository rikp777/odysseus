// Custom route favicon/title metadata loaded before the shared route-icon script.
(function(){
  window.__odysseusCustomRouteMetadata = {
    shapes: {
      '/logbook': function(ac) {
        return "<path d='M6 4 H22 V28 H6 A2 2 0 0 1 4 26 V6 A2 2 0 0 1 6 4 Z' fill='none' stroke='" + ac + "' stroke-width='2.5'/>" +
          "<path d='M8 4 V28' fill='none' stroke='" + ac + "' stroke-width='2'/>" +
          "<line x1='12' y1='10' x2='19' y2='10' stroke='" + ac + "' stroke-width='2'/>" +
          "<line x1='12' y1='15' x2='19' y2='15' stroke='" + ac + "' stroke-width='2'/>" +
          "<line x1='12' y1='20' x2='17' y2='20' stroke='" + ac + "' stroke-width='2'/>";
      },
      '/logbook/atlas': function(ac) {
        return "<circle cx='9' cy='8' r='3' fill='none' stroke='" + ac + "' stroke-width='2.5'/>" +
          "<path d='M3 23 V21 A5 5 0 0 1 8 16 H10' fill='none' stroke='" + ac + "' stroke-width='2.5' stroke-linecap='round'/>" +
          "<path d='M15 5 L26 9 L15 13 L4 9 Z' fill='none' stroke='" + ac + "' stroke-width='2.5' stroke-linejoin='round'/>" +
          "<path d='M4 9 V20 L15 27 L26 20 V9' fill='none' stroke='" + ac + "' stroke-width='2' stroke-linejoin='round'/>" +
          "<path d='M15 13 V27' fill='none' stroke='" + ac + "' stroke-width='2'/>";
      },
    },
    titles: {
      '/logbook': 'Logbook - Odysseus',
      '/logbook/atlas': 'People & Places - Odysseus',
    },
  };
})();
