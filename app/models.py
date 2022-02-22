from flask import url_for, Markup
from mongoengine import Document
from mongoengine import StringField, ImageField, FloatField, URLField, ReferenceField, IntField, BooleanField, ListField

class Franchise(Document):
    name = StringField(required=True)
    link = URLField()
    image = ImageField(thumbnail_size=(100,50,False),collection_name='franchise_images')
    start_year = IntField(min_value=1900, max_value=3000, required=True)
    end_year = IntField(min_value=1900, max_value=3000)

    def __unicode__(self):
        return self.name

    def __repr__(self):
        return self.name

    def image_show(self):
        if self.image:
            return Markup('<a href="' + url_for('FranchiseModelView.show',pk=str(self.id)) + \
                      '" class="thumbnail"><img src="' + url_for('FranchiseModelView.img', pk=str(self.id)) + \
                      '" alt="Photo" class="img-rounded img-responsive"></a>')
        else:
            return Markup('')

    def image_thumb_show(self):
        print(self.image, self.id)
        if self.image:
            return Markup('<a href="' + url_for('FranchiseModelView.show',pk=str(self.id)) + \
                      '" class="thumbnail"><img src="' + url_for('FranchiseModelView.img_thumb', pk=str(self.id)) + \
                      '" alt="Photo" class="img-rounded img-responsive"></a>')
        else:
            return Markup('')

    def link_show(self):
        return Markup(
            '<a href="' + str(self.link) + '">' + str(self.link) + '</a>'
        )
        
    def figure_list(self):
        return Markup(
            '<a href="' + url_for('FigureModelView.list',_flt_0_franchise=str(self.id)) + '">Search Figures</a>'
        )
        
class Faction(Document):
    name = StringField(required=True)
    image = ImageField(thumbnail_size=(100,50,False),collection_name='faction_images')

    def __unicode__(self):
        return self.name

    def __repr__(self):
        return self.name

    def image_show(self):
        if self.image:
            return Markup('<a href="' + url_for('FactionModelView.show',pk=str(self.id)) + \
                      '" class="thumbnail"><img src="' + url_for('FactionModelView.img', pk=str(self.id)) + \
                      '" alt="Photo" class="img-rounded img-responsive"></a>')
        else:
            return Markup('')

    def image_thumb_show(self):
        print(self.image, self.id)
        if self.image:
            return Markup('<a href="' + url_for('FactionModelView.show',pk=str(self.id)) + \
                      '" class="thumbnail"><img src="' + url_for('FactionModelView.img_thumb', pk=str(self.id)) + \
                      '" alt="Photo" class="img-rounded img-responsive"></a>')
        else:
            return Markup('')

    def figure_list(self):
        return Markup(
            '<a href="' + url_for('FigureModelView.list',_flt_0_faction=str(self.id)) + '">Search Figures</a>'
        )
        
class Tooling(Document):
    name = StringField(max_length=60, required=True, unique=True)

    def __unicode__(self):
        return self.name
        
    def __repr__(self):
        return self.name

class Accessory(Document):
    name = StringField(max_length=60, required=True, unique=True)

    def __unicode__(self):
        return self.name
        
    def __repr__(self):
        return self.name

class Category(Document):
    name = StringField(max_length=60, required=True, unique=True)

    def __unicode__(self):
        return self.name
        
    def __repr__(self):
        return self.name

class TFWikiLink(Document):
    name = StringField(required=True)
    link = URLField(required=True)

    def __unicode__(self):
        ls = self.link.split('#')
        if len(ls) > 1:
            n = ls[0].split('/')[-1]
            if (n == 'toys' or n == 'Generations_toys':
                n = ls[0].split('/')[-2]
            sn = n.split('_(')
            if len(sn) > 1:
                return self.name+' ('+sn[-1]+' @ '+ls[-1].replace('_',' ')+' [figure]'
            else:
                return self.name+' @ '+ls[-1].replace('_',' ')+' [figure]'
        n = self.link.split('/')[-1]
        sn = n.split('_(')
        if len(sn) > 1:
            return self.name+' ('+sn[-1]+' [character]'
        else:
            return self.name+' [character]'
            
    def link_type(self):
        ls = self.link.split('#')
        if len(ls) > 1:
            return 'Figure ('+ls[-1].replace('_',' ')+')'
        n = self.link.split('/')[-1]
        sn = n.split('_(')
        if len(sn) > 1:
            return 'Character ('+sn[-1]
        else:
            return 'Character'
            

class Figure(Document):
    name = StringField(required=True)
    release_year = IntField(min_value=1900, max_value=3000, required=True)
    image = ImageField(thumbnail_size=(300,300,False),collection_name='figure_images')
    figure_link = ReferenceField('TFWikiLink')
    franchise = ListField(ReferenceField('Franchise'), required=True)
    character = ReferenceField('TFWikiLink', required=True)
    tooling = ListField(ReferenceField('Tooling'), required=True)
    faction = ReferenceField('Faction', required=True)
    exclusive_to = StringField()
    history = ListField(ReferenceField('TFWikiLink'))
    packed_with = ListField(ReferenceField('TFWikiLink'))
    hasbro_id = StringField()
    takara_id = StringField()
    gestalt_of = ListField(ReferenceField('self'))
    accessories = ListField(ReferenceField('Accessory'))
    categories = ListField(ReferenceField('Category'))
    condition = StringField()
    quantity = IntField(min_value=1, default=1)

    def __unicode__(self):
        return self.name

    def __repr__(self):
        return self.name

    def image_show(self):
        if self.image:
            return Markup('<a href="' + url_for('FigureModelView.show',pk=str(self.id)) + \
                      '" class="thumbnail"><img src="' + url_for('FigureModelView.img', pk=str(self.id)) + \
                      '" alt="Photo" class="img-rounded img-responsive"></a>')
        else:
            return Markup('')

    def image_thumb_show(self):
        print(self.image, self.id)
        if self.image:
            return Markup('<a href="' + url_for('FigureModelView.show',pk=str(self.id)) + \
                      '" class="thumbnail"><img src="' + url_for('FigureModelView.img_thumb', pk=str(self.id)) + \
                      '" alt="Photo" class="img-rounded img-responsive"></a>')
        else:
            return Markup('')

    def faction_show(self):
        return Markup(
            '<p>' + str(self.faction) + '</p>' + \
            '<img src="' + url_for('FactionModelView.img_thumb', pk=str(self.faction.id)) + \
            '" alt="' + str(self.faction.name) + '" class="img-responsive">'
        )
    
    def link_show(self, link):
        return Markup(
            '<a href="' + str(link.link) + '">' + str(link) + '</a>'
        )
        
    def link_list_show(self, link_list, hasimg=False):
        m = '<table class="table table-condensed table-striped"><tbody>'
        for l in link_list:
            m += '<tr><td><a href="' + str(l.link) + '">'
            if hasimg and l.image:
                m+= '<img src="' + url_for('FranchiseModelView.img', pk=str(l.id)) + \
                '" alt="' + str(l.name) + '" class="img-responsive"><br/>'
            m += str(l) + '</a></td></tr>'
        m += '</tbody></table>'
        return Markup(m)

    def character_show(self):
        return self.link_show(self.character)
        
    def franchise_show(self):
        return self.link_list_show(self.franchise,True)

    def figure_link_show(self):
        return self.link_show(self.figure_link)
        
    def history_show(self):
        return self.link_list_show(self.history)
        
    def packed_with_show(self):
        return self.link_list_show(self.packed_with)
        
